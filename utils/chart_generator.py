# chart_generator.py — matplotlib 기반 통계 차트 생성

import io
import matplotlib
matplotlib.use('Agg')  # 서버 환경 (GUI 없음)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def _parse_dates(stats: list[dict]) -> list[datetime]:
    return [datetime.strptime(s["date"], "%Y-%m-%d") for s in stats]


def generate_usage_chart(stats: list[dict]) -> io.BytesIO:
    """일별 호출 수 + 캐시 히트 차트."""
    if not stats:
        return _empty_chart("데이터가 없습니다")

    dates = _parse_dates(stats)
    calls = [s["total_calls"] for s in stats]
    hits = [s["cache_hits"] for s in stats]

    fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
    fig.patch.set_facecolor('#2C2F33')
    ax.set_facecolor('#23272A')

    ax.bar(dates, calls, width=0.6, label='API 호출', color='#5865F2', alpha=0.9)
    ax.bar(dates, hits, width=0.6, label='캐시 히트', color='#57F287', alpha=0.9, bottom=calls)

    ax.set_title('일별 번역 요청량', color='white', fontsize=14, pad=10)
    ax.set_ylabel('건수', color='white')
    ax.legend(loc='upper left', facecolor='#2C2F33', edgecolor='#5865F2', labelcolor='white')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45, color='white', fontsize=8)
    plt.yticks(color='white')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#5865F2')

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_cost_chart(stats: list[dict]) -> io.BytesIO:
    """일별 비용 추이 차트."""
    if not stats:
        return _empty_chart("데이터가 없습니다")

    dates = _parse_dates(stats)
    costs = [s["cost_usd"] for s in stats]

    # 누적 비용
    cumulative = []
    total = 0
    for c in costs:
        total += c
        cumulative.append(total)

    fig, ax1 = plt.subplots(figsize=(10, 4), dpi=100)
    fig.patch.set_facecolor('#2C2F33')
    ax1.set_facecolor('#23272A')

    ax1.bar(dates, costs, width=0.6, label='일별 비용', color='#FEE75C', alpha=0.9)
    ax1.set_ylabel('일별 비용 ($)', color='#FEE75C')
    ax1.tick_params(axis='y', labelcolor='#FEE75C')

    ax2 = ax1.twinx()
    ax2.plot(dates, cumulative, color='#ED4245', linewidth=2, marker='o', markersize=4, label='누적 비용')
    ax2.set_ylabel('누적 비용 ($)', color='#ED4245')
    ax2.tick_params(axis='y', labelcolor='#ED4245')

    ax1.set_title('일별 API 비용', color='white', fontsize=14, pad=10)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left',
               facecolor='#2C2F33', edgecolor='#5865F2', labelcolor='white')

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45, color='white', fontsize=8)
    for spine in ax1.spines.values():
        spine.set_color('#5865F2')
    for spine in ax2.spines.values():
        spine.set_color('#5865F2')

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_efficiency_chart(stats: list[dict]) -> io.BytesIO:
    """캐시 절약률 + 오타 교정 비율 차트."""
    if not stats:
        return _empty_chart("데이터가 없습니다")

    dates = _parse_dates(stats)

    cache_rates = []
    for s in stats:
        total = s["total_calls"] + s["cache_hits"]
        rate = (s["cache_hits"] / total * 100) if total > 0 else 0
        cache_rates.append(rate)

    typo_rates = []
    for s in stats:
        calls = s["total_calls"]
        rate = (s["typo_corrections"] / calls * 100) if calls > 0 else 0
        typo_rates.append(rate)

    fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
    fig.patch.set_facecolor('#2C2F33')
    ax.set_facecolor('#23272A')

    ax.plot(dates, cache_rates, color='#57F287', linewidth=2, marker='o', markersize=4, label='캐시 절약률 (%)')
    ax.plot(dates, typo_rates, color='#EB459E', linewidth=2, marker='s', markersize=4, label='오타 교정 비율 (%)')

    ax.set_title('효율성 지표', color='white', fontsize=14, pad=10)
    ax.set_ylabel('%', color='white')
    ax.set_ylim(0, 100)
    ax.legend(loc='upper left', facecolor='#2C2F33', edgecolor='#5865F2', labelcolor='white')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45, color='white', fontsize=8)
    plt.yticks(color='white')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#5865F2')

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def _empty_chart(message: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
    fig.patch.set_facecolor('#2C2F33')
    ax.set_facecolor('#23272A')
    ax.text(0.5, 0.5, message, ha='center', va='center', color='white', fontsize=16)
    ax.axis('off')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf
