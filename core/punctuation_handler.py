# punctuation_handler.py — 문장부호 분리/복원 (의미 부호 vs 강조 부호)

import re
from typing import Optional


def analyze_punctuation(text: str) -> tuple[str, Optional[str], str]:
    """
    텍스트를 본문 / 의미 부호 / 강조 부호로 분리.

    의미 부호 (?): 문장의 뜻을 바꿈 → AI에게 넘김, 캐시 키에 포함
    강조 부호 (! ~ .): 개수만 다름 → CPU에서 복원, 캐시 키에서 제외

    Args:
        text: 원본 텍스트

    Returns:
        (순수_텍스트, 의미_부호_or_None, 강조_부호_원본_문자열)
    """
    # 문장 끝 부호 패턴 (반각/전각 포함, 말줄임표 … 추가)
    match = re.search(r'([!?~.！？～。…]+)\s*$', text)

    if not match:
        return text, None, ""

    raw_puncs = match.group(1)
    clean_text = text[:match.start()].rstrip()

    # 의미 부호 추출
    semantic_mark = None
    if '?' in raw_puncs or '？' in raw_puncs:
        semantic_mark = '?'

    # 강조 부호 추출 (? 제거한 나머지 원본 순서 보관)
    emphasis_raw = re.sub(r'[?？]', '', raw_puncs)

    return clean_text, semantic_mark, emphasis_raw


def build_ai_input(clean_text: str, semantic_mark: Optional[str]) -> str:
    """
    AI에게 전달할 텍스트 생성.
    의미 부호가 있으면 텍스트에 포함.

    Args:
        clean_text: 순수 텍스트
        semantic_mark: 의미 부호 ("?" 또는 None)

    Returns:
        AI 입력용 텍스트
    """
    if semantic_mark in ['?', '？']:
        return f"{clean_text}?"
    return clean_text


def restore_punctuation(translated_text: str, semantic_mark: Optional[str], emphasis_raw: str) -> str:
    """
    번역 결과에 강조 부호를 복원.
    AI가 의미 부호(?)는 이미 처리했으므로, 강조 부호만 CPU에서 붙임.

    Args:
        translated_text: AI 번역 결과
        semantic_mark: 의미 부호 ("?" 또는 None)
        emphasis_raw: 원본 강조 부호 문자열

    Returns:
        최종 번역 텍스트
    """
    # AI가 임의로 추가한 문장부호 제거 (의미 부호 ? 포함하여 말줄임표까지 모두 제거)
    # ! ~ . … ？ ！ 。 등 모든 끝 부호 제거 후 CPU가 보관한 원본으로 교체
    cleaned = re.sub(r'[!?~.！？～。…\s]+$', '', translated_text)

    # 원본에 의미 부호가 있었으면 붙여줌 (AI가 이미 붙였을 수도 있지만, 위에서 제거했으므로 수동 복원)
    res = cleaned
    if semantic_mark:
        res += semantic_mark
    
    return res + emphasis_raw
