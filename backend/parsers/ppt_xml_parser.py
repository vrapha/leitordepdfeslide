"""
PPTXMLParser — Fallback simples: detecta resposta quando os shapes têm
o nome exato "gabarito" e "alternativas" no XML.
"""
import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class PPTXMLParser:
    def __init__(self, pptx_path: str):
        self.pptx_path = pptx_path

    def unpack_pptx(self, dest_dir: str):
        with zipfile.ZipFile(self.pptx_path, "r") as z:
            z.extractall(dest_dir)

    def get_slide_order(self, unpacked_dir: str) -> list[str]:
        prs_path = os.path.join(unpacked_dir, "ppt", "presentation.xml")
        rels_path = os.path.join(unpacked_dir, "ppt", "_rels", "presentation.xml.rels")

        rid_to_file: dict[str, str] = {}
        if os.path.exists(rels_path):
            try:
                tree = ET.parse(rels_path)
                for rel in tree.getroot().iter(
                    "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
                ):
                    if "slide" in rel.get("Type", "") and "slideLayout" not in rel.get("Type", ""):
                        rid = rel.get("Id")
                        target = rel.get("Target", "")
                        if not target.startswith("/"):
                            target = os.path.join(unpacked_dir, "ppt", target)
                        else:
                            if target.startswith("/ppt/"):
                                target = target[1:]
                            target = os.path.join(unpacked_dir, target)
                        rid_to_file[rid] = os.path.normpath(target)
            except Exception as e:
                print(f"[XMLParser] Error parsing rels: {e}")

        ordered: list[str] = []
        if os.path.exists(prs_path):
            try:
                tree = ET.parse(prs_path)
                ns_prs = "http://schemas.openxmlformats.org/presentationml/2006/main"
                for sld_id in tree.getroot().iter(f"{{{ns_prs}}}sldId"):
                    rid = sld_id.get(f"{{{NS_R}}}id")
                    if rid and rid in rid_to_file:
                        ordered.append(rid_to_file[rid])
            except Exception as e:
                print(f"[XMLParser] Error parsing presentation.xml: {e}")

        if not ordered:
            slides_dir = os.path.join(unpacked_dir, "ppt", "slides")
            if os.path.isdir(slides_dir):
                files = sorted(
                    [f for f in os.listdir(slides_dir) if f.startswith("slide") and f.endswith(".xml")],
                    key=lambda x: int("".join(filter(str.isdigit, x)) or 0),
                )
                ordered = [os.path.join(slides_dir, f) for f in files]

        return ordered

    def parse_slide_xml(self, slide_path: str) -> str | None:
        try:
            root = ET.parse(slide_path).getroot()
            shapes: dict[str, dict] = {}

            for sp in root.iter(f"{{{NS_P}}}sp"):
                name = ""
                for elem in sp.iter():
                    if "cNvPr" in elem.tag:
                        name = elem.get("name", "")
                        break

                name_key = name.lower()
                if name_key not in ("gabarito", "alternativas", "codigo"):
                    continue

                pos = None
                xfrm = sp.find(f".//{{{NS_A}}}xfrm")
                if xfrm is not None:
                    off = xfrm.find(f"{{{NS_A}}}off")
                    ext = xfrm.find(f"{{{NS_A}}}ext")
                    if off is not None:
                        pos = {
                            "x": int(off.get("x", 0)),
                            "y": int(off.get("y", 0)),
                            "cx": int(ext.get("cx", 0)) if ext is not None else 0,
                            "cy": int(ext.get("cy", 0)) if ext is not None else 0,
                        }

                paras: list[str] = []
                for para in sp.iter(f"{{{NS_A}}}p"):
                    para_texts = [t.text for t in para.iter(f"{{{NS_A}}}t") if t.text]
                    if para_texts:
                        paras.append("".join(para_texts))

                shapes[name_key] = {"pos": pos, "paras": paras}

            if "gabarito" not in shapes or "alternativas" not in shapes:
                return None

            gab_pos = shapes["gabarito"]["pos"]
            alt_pos = shapes["alternativas"]["pos"]
            paras = shapes["alternativas"]["paras"]
            n = len(paras)

            if not gab_pos or not alt_pos or n == 0:
                return None

            gab_center_y = gab_pos["y"] + gab_pos["cy"] / 2
            relative_y = gab_center_y - alt_pos["y"]
            option_height = alt_pos["cy"] / n
            option_idx = max(0, min(n - 1, int(relative_y / option_height)))
            return LETTERS[option_idx] if option_idx < len(LETTERS) else str(option_idx + 1)

        except Exception as e:
            print(f"[XMLParser] Error parsing {slide_path}: {e}")
            return None

    def analyze(self) -> dict[int, str]:
        results: dict[int, str] = {}
        if not os.path.exists(self.pptx_path):
            return results
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                self.unpack_pptx(tmpdir)
                slides = self.get_slide_order(tmpdir)
                for idx, slide_path in enumerate(slides):
                    if not os.path.exists(slide_path):
                        continue
                    ans = self.parse_slide_xml(slide_path)
                    if ans:
                        results[idx] = ans
        except Exception as e:
            print(f"[XMLParser] Error: {e}")
        return results
