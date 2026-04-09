"""
ChatGPT Bot Service — Playwright automation para ChatGPT.
Portado do chat_bot.py original. Roda em thread síncrona (executor).
"""
import os
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
CHATGPT_AUTH_FILE = str(SESSIONS_DIR / "auth.json")


class ChatGPTBot:
    def __init__(self, headless: bool = False, logger: Callable = print):
        self.headless = headless
        self.logger = logger
        self.browser = None
        self.page = None
        self.playwright = None
        self.context = None
        self.auth_file = CHATGPT_AUTH_FILE

    def log(self, msg: str):
        self.logger(f"[Bot] {msg}")

    def start(self):
        self.playwright = sync_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,800",
            "--no-sandbox",
        ]

        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=args,
        )

        context_kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        if os.path.exists(self.auth_file):
            self.log(f"Carregando sessão de {self.auth_file}")
            context_kwargs["storage_state"] = self.auth_file
        else:
            self.log("Sem sessão salva. Iniciando login manual.")

        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        self.log("Navegando para ChatGPT...")
        try:
            self.page.goto("https://chatgpt.com/", wait_until="commit", timeout=45000)
        except Exception as e:
            self.log(f"Erro de navegação: {e}")

    def ensure_login(self, timeout_seconds: int = 300):
        """Aguarda login manual e salva sessão."""
        self.log("Aguardando login... (faça login manualmente se necessário)")
        for i in range(timeout_seconds):
            try:
                if (
                    self.page.is_visible("#prompt-textarea")
                    or self.page.is_visible("div[contenteditable='true']")
                    or self.page.is_visible("button[data-testid='send-button']")
                ):
                    self.log("Login detectado!")
                    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
                    self.context.storage_state(path=self.auth_file)
                    self.log(f"Sessão salva em {self.auth_file}")
                    return
            except Exception:
                pass
            if i > 0 and i % 10 == 0:
                self.log(f"Aguardando login ({i}s)...")
            time.sleep(1)
        raise TimeoutError("Timeout aguardando login no ChatGPT.")

    def restart(self):
        self.log("Reiniciando bot...")
        try:
            self.close()
        except Exception:
            pass
        time.sleep(2)
        self.start()
        self.ensure_login()

    def new_conversation(self):
        """Reinicia a conversa navegando para a página inicial (evita DOM buildup)."""
        self.log("Nova conversa (reset DOM)...")
        try:
            self.page.goto("https://chatgpt.com/", wait_until="commit", timeout=30000)
            time.sleep(3)
            self.page.locator("#prompt-textarea").first.wait_for(state="attached", timeout=15000)
            self.log("Pronto para nova conversa.")
        except Exception as e:
            self.log(f"Erro ao iniciar nova conversa: {e}. Reiniciando...")
            self.restart()

    def query(self, prompt: str) -> str:
        """Envia prompt e aguarda resposta completa."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.page or self.page.is_closed():
                    self.restart()

                composer = self.page.locator("#prompt-textarea").first
                composer.wait_for(state="attached", timeout=15000)
                composer.click(force=True)
                time.sleep(0.5)

                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Backspace")
                time.sleep(0.3)

                self.page.keyboard.insert_text(prompt)
                time.sleep(1.0)
                self.page.keyboard.press("Enter")

                self.log("Aguardando resposta do ChatGPT...")

                try:
                    initial_count = len(self.page.locator(".markdown").all())
                except Exception:
                    initial_count = 0

                start_wait = time.time()
                max_wait = 300
                last_text = ""
                stable_count = 0
                current_text = ""

                while (time.time() - start_wait) < max_wait:
                    if self.page.is_closed():
                        raise RuntimeError("Página fechada durante query")

                    current_msgs = self.page.locator(".markdown").all()
                    if len(current_msgs) > initial_count:
                        current_text = current_msgs[-1].text_content() or ""
                        if current_text == last_text and len(current_text) > 20:
                            stable_count += 1
                            if stable_count >= 5:
                                self.log("Resposta completa.")
                                return current_text
                        else:
                            stable_count = 0
                        last_text = current_text
                    else:
                        if (time.time() - start_wait) > 15:
                            self.page.keyboard.press("Enter")

                    time.sleep(2)

                self.log("Timeout aguardando resposta.")
                if len(current_text) > 30:
                    return current_text

            except Exception as e:
                self.log(f"Tentativa {attempt + 1} falhou: {e}")
                if attempt < max_retries - 1:
                    self.restart()
                    continue
                return f"Error: {e}"

        return "Error: Max retries exceeded."

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
