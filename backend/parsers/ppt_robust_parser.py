"""
RobustPPTXParser — Parser XML primário (mais preciso).
Lê o PPTX como ZIP e analisa o XML cru de cada slide.
Versão web: sem pywin32/COM. PDF export via LibreOffice headless.
"""
import zipfile
import xml.etree.ElementTree as ET
import re
import subprocess
from pathlib import Path
from typing import Callable

try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


class RobustPPTXParser:
    def __init__(self, pptx_path: str, logger: Callable | None = None):
        self.pptx_path = pptx_path
        self.logger = logger or print
        self._pdf_doc = None

    def analyze(self) -> dict[int, str]:
        answers: dict[int, str] = {}
        try:
            with zipfile.ZipFile(self.pptx_path, "r") as z:
                slide_files = sorted(
                    [f for f in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", f)],
                    key=lambda s: int(re.search(r"(\d+)", s.split("/")[-1]).group(1)),
                )
                for s_file in slide_files:
                    try:
                        s_num = int(re.search(r"(\d+)", s_file.split("/")[-1]).group(1))
                        xml_content = z.read(s_file)
                        ans = self._detect_answer(xml_content, s_num)
                        if ans:
                            answers[s_num - 1] = ans
                    except Exception as e:
                        self.logger(f"[RobustXML] Err {s_file}: {e}")
        except Exception as e:
            self.logger(f"[RobustXML] Err: {e}")
        return answers

    def _detect_answer(self, xml_content: bytes, slide_num: int) -> str | None:
        try:
            root = ET.fromstring(xml_content)
            shapes = root.findall(".//p:sp", NS)

            red_markers: list[dict] = []
            alt_shape: dict | None = None
            all_text_shapes: list[dict] = []

            for sp in shapes:
                info = self._get_shape_info(sp)
                if info["has_red_outline"]:
                    red_markers.append(info)
                    continue
                name_lower = info["name"].lower()
                if "alternativas" in name_lower or "alternativa" in name_lower:
                    alt_shape = info
                if info["text"].strip():
                    all_text_shapes.append(info)

            if not red_markers:
                return None
            if alt_shape is None:
                alt_shape = self._find_alternatives_shape(all_text_shapes)
            if alt_shape is None:
                return None

            return self._calculate_answer(red_markers, alt_shape, slide_num, all_text_shapes)
        except Exception as e:
            self.logger(f"[RobustXML] Exception slide {slide_num}: {e}")
            return None

    def _get_shape_info(self, sp) -> dict:
        info: dict = {
            "name": "", "geom": "",
            "y": 0, "cy": 0, "x": 0, "cx": 0,
            "has_red_outline": False,
            "text": "", "paragraphs": [],
            "element": sp,
        }

        nvPr = sp.find("p:nvSpPr/p:cNvPr", NS)
        if nvPr is not None:
            info["name"] = nvPr.attrib.get("name", "")

        prstGeom = sp.find(".//a:prstGeom", NS)
        if prstGeom is not None:
            info["geom"] = prstGeom.attrib.get("prst", "")

        xfrm = sp.find(".//a:xfrm", NS)
        if xfrm is not None:
            off = xfrm.find("a:off", NS)
            ext = xfrm.find("a:ext", NS)
            if off is not None:
                info["x"] = int(off.attrib.get("x", 0))
                info["y"] = int(off.attrib.get("y", 0))
            if ext is not None:
                info["cx"] = int(ext.attrib.get("cx", 0))
                info["cy"] = int(ext.attrib.get("cy", 0))

        # Detectar contorno vermelho
        ln = sp.find(".//a:ln", NS)
        if ln is not None:
            no_fill = ln.find("a:noFill", NS)
            if no_fill is None:
                sf = ln.find("a:solidFill", NS)
                if sf is not None:
                    srgb = sf.find("a:srgbClr", NS)
                    if srgb is not None:
                        color = srgb.attrib.get("val", "").upper()
                        if len(color) >= 6:
                            r = int(color[0:2], 16)
                            g = int(color[2:4], 16)
                            b = int(color[4:6], 16)
                            if r > 150 and g < 100 and b < 100:
                                info["has_red_outline"] = True

        # Detectar preenchimento vermelho
        for solid in sp.findall(".//a:solidFill", NS):
            srgb = solid.find("a:srgbClr", NS)
            if srgb is not None:
                color = srgb.attrib.get("val", "").upper()
                if len(color) >= 6:
                    r = int(color[0:2], 16)
                    g = int(color[2:4], 16)
                    b = int(color[4:6], 16)
                    if r > 150 and g < 100 and b < 100:
                        info["has_red_outline"] = True

        txBody = sp.find("p:txBody", NS)
        texts: list[str] = []
        para_list: list[str] = []
        if txBody is not None:
            for p in txBody.findall("a:p", NS):
                t_runs = [t.text for t in p.findall(".//a:t", NS) if t.text]
                para_text = "".join(t_runs).strip()
                if para_text:
                    para_list.append(para_text)
                    texts.append(para_text)
        info["text"] = "\n".join(texts)
        info["paragraphs"] = para_list
        return info

    def _find_alternatives_shape(self, text_shapes: list[dict]) -> dict | None:
        letter_pat = re.compile(r"^[A-Ea-e][\)\.\-\:]")
        best = None
        best_count = 0
        for info in text_shapes:
            count = sum(1 for p in info["paragraphs"] if letter_pat.match(p))
            if count >= 2 and count > best_count:
                best = info
                best_count = count
        if best is None and text_shapes:
            best = max(text_shapes, key=lambda s: s["cy"])
        return best

    def _get_pdf_doc(self):
        """Converte PPTX para PDF via LibreOffice headless."""
        if self._pdf_doc:
            return self._pdf_doc
        if not FITZ_AVAILABLE:
            return None
        try:
            abs_ppt = str(Path(self.pptx_path).resolve())
            output_dir = str(Path(abs_ppt).parent)
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf",
                 "--outdir", output_dir, abs_ppt],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                pdf_path = abs_ppt.replace(".pptx", "_robust_visual_temp.pdf")
                alt_path = abs_ppt.replace(".pptx", ".pdf")
                for p in [pdf_path, alt_path]:
                    if Path(p).exists():
                        self._pdf_doc = fitz.open(p)
                        return self._pdf_doc
        except Exception as e:
            self.logger(f"[RobustXML] PDF conversion failed: {e}")
        return None

    def _calculate_answer(
        self,
        red_markers: list[dict],
        alt_shape: dict,
        slide_num: int,
        all_text_shapes: list[dict] | None = None,
    ) -> str | None:
        alt_y = alt_shape["y"]
        alt_h = alt_shape["cy"]
        if alt_h == 0:
            return None

        # Tentativa via PDF visual (se LibreOffice disponível)
        pdf_doc = self._get_pdf_doc()
        if pdf_doc and FITZ_AVAILABLE:
            try:
                pdf_page_idx = slide_num - 1
                if 0 <= pdf_page_idx < len(pdf_doc):
                    page = pdf_doc[pdf_page_idx]
                    for marker in red_markers:
                        rect = fitz.Rect(
                            marker["x"] / 12700.0,
                            marker["y"] / 12700.0,
                            (marker["x"] + marker["cx"]) / 12700.0,
                            (marker["y"] + marker["cy"]) / 12700.0,
                        )
                        vis_text = page.get_textbox(rect).strip().upper()
                        m = re.search(r"([A-E])", vis_text)
                        if m:
                            letter = m.group(1)
                            self.logger(f"[RobustXML] Slide {slide_num}: Visual HIT -> {letter}")
                            return letter
            except Exception as e:
                self.logger(f"[RobustXML] PDF read error: {e}")

        for marker in red_markers:
            marker_cy = marker["y"] + (marker["cy"] / 2)

            # Tentativa 1: caixas separadas
            if all_text_shapes:
                alt_boxes = [
                    s for s in all_text_shapes
                    if re.match(r"^([A-E])\s*[).\-]", s["text"].strip().upper())
                ]
                if len(alt_boxes) >= 3:
                    alt_boxes.sort(key=lambda x: x["y"])
                    best_letter = None
                    min_score = float("inf")
                    for s in alt_boxes:
                        s_cy = s["y"] + s["cy"] / 2
                        score = abs(marker_cy - s_cy)
                        if score < min_score:
                            min_score = score
                            m = re.search(r"^([A-E])", s["text"].strip().upper())
                            if m:
                                best_letter = m.group(1)
                    if best_letter:
                        self.logger(f"[RobustXML] Slide {slide_num}: Separadas -> {best_letter}")
                        return best_letter

            # Tentativa 2: bloco único
            sp_element = alt_shape.get("element")
            ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
            ns_p_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"

            raw_paras_text: list[str] = []
            raw_paras_original: list[str] = []
            if sp_element is not None:
                txBody = sp_element.find(f"{{{ns_p_ns}}}txBody")
                if txBody is None:
                    txBody = sp_element.find(f"{{{ns_a}}}txBody")
                if txBody is not None:
                    for p_elem in txBody.findall(f"{{{ns_a}}}p"):
                        t_runs = [t.text for t in p_elem.findall(f".//{{{ns_a}}}t") if t.text]
                        full = "".join(t_runs)
                        raw_paras_original.append(full)
                        raw_paras_text.append(full.strip())

            if not raw_paras_text:
                raw_paras_text = [p.strip() for p in alt_shape.get("paragraphs", [])]
                raw_paras_original = list(alt_shape.get("paragraphs", []))

            if not raw_paras_text:
                continue

            para_lines: list[float] = []
            alt_map: dict[int, str] = {}
            text_indices = [i for i, t in enumerate(raw_paras_text) if t]
            alt_indices = text_indices[-5:] if len(text_indices) >= 5 else text_indices

            for i, txt in enumerate(raw_paras_text):
                orig = raw_paras_original[i] if i < len(raw_paras_original) else txt
                m = re.search(r"^\s*([A-E])[\)\.\-]", orig)
                if m:
                    alt_map[i] = m.group(1).upper()

                if not txt:
                    para_lines.append(1.5)
                elif i in alt_indices:
                    para_lines.append(1.0 + len(txt) / 90.0)
                else:
                    lines = sum(max(1.0, len(seg) // 85 + 1.0) for seg in txt.split("\n"))
                    para_lines.append(lines)

            if sum(para_lines) == 0:
                continue

            unit_h = alt_h / sum(para_lines)
            current_y = alt_y
            para_coords: dict[int, float] = {}
            for i, lines in enumerate(para_lines):
                ph = lines * unit_h
                para_coords[i] = current_y + ph / 2.0
                current_y += ph

            best_letter = None
            min_dist = float("inf")

            if len(alt_map) >= 3:
                for idx, letter in alt_map.items():
                    dist = abs(marker_cy - para_coords[idx])
                    if dist < min_dist:
                        min_dist = dist
                        best_letter = letter
            else:
                letters = ["A", "B", "C", "D", "E"]
                for i, p_idx in enumerate(alt_indices):
                    dist = abs(marker_cy - para_coords[p_idx])
                    if dist < min_dist:
                        min_dist = dist
                        best_letter = letters[i] if i < len(letters) else None

            if best_letter:
                self.logger(f"[RobustXML] Slide {slide_num}: BlocoUnico -> {best_letter}")
                return best_letter

        return None
