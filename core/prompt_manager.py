import json
import os
import time
from utils.logger import bot_log

class PromptManager:
    _instance = None
    _prompts = {}
    _last_mtime = 0
    _file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompts.json")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptManager, cls).__new__(cls)
            cls._instance._load_prompts()
        return cls._instance

    def _load_prompts(self):
        """JSON 파일에서 프롬프트를 로드합니다. 파일이 없거나 오류 시 빈 딕셔너리를 반환합니다."""
        try:
            if not os.path.exists(self._file_path):
                bot_log.error(f"[PROMPTS] File not found: {self._file_path}")
                return

            current_mtime = os.path.getmtime(self._file_path)
            # 파일이 수정되었을 때만 로드 (Hot-reload)
            if current_mtime > self._last_mtime:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self._prompts = json.load(f)
                self._last_mtime = current_mtime
                bot_log.info(f"[PROMPTS] Refreshed prompts from {self._file_path} (mtime: {current_mtime})")
        except Exception as e:
            bot_log.error(f"[PROMPTS-ERROR] Failed to load prompts: {e}")

    def get_prompt(self, category: str, key: str, default: str = "") -> str:
        """특정 카테고리와 키에 해당하는 프롬프트를 가져옵니다."""
        self._load_prompts() # mtime 체크 및 필요시 리로드
        return self._prompts.get(category, {}).get(key, default)

    def save_prompt(self, category: str, key: str, value: str) -> bool:
        """프롬프트를 수정하고 파일에 저장합니다. (AI가 스스로 호출 가능)"""
        try:
            self._load_prompts()
            if category not in self._prompts:
                self._prompts[category] = {}
            self._prompts[category][key] = value

            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._prompts, f, indent=2, ensure_ascii=False)
            
            # 본인이 쓴 것은 본인이 인지하도록 mtime 즉시 갱신
            self._last_mtime = os.path.getmtime(self._file_path)
            bot_log.info(f"[PROMPTS] Successfully updated [{category}][{key}]")
            return True
        except Exception as e:
            bot_log.error(f"[PROMPTS-SAVE-ERROR] {e}")
            return False

# 싱글톤 인스턴스 노출
prompt_manager = PromptManager()
