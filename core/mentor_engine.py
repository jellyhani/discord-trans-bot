import json
import re
import asyncio
from datetime import datetime
from utils.logger import mentor_log, bot_log
from database.database import get_all_developer_knowledge, add_pending_inquiry, get_bot_trait, set_bot_trait
from database.user_personas import get_user_persona
from database.chat_logger import get_mentor_logs, get_active_session_id, get_sessions, record_mentor_log

class MentorEngine:
    def __init__(self, bot):
        self.bot = bot

    async def generate_response(self, user_id: int, nickname: str, content: str, original_message=None, reference_content: str = None):
        """AI를 통해 답변을 생성하고 도구를 실행합니다."""
        from core.translator import _get_client
        client = _get_client()
        
        # 1. 데이터 로드
        persona_data = await get_user_persona(user_id)
        user_instruction = persona_data["mentor_instruction"] if persona_data else None
        history_logs = await get_mentor_logs(user_id, limit=5)
        
        active_sid = await get_active_session_id(user_id)
        all_sessions = await get_sessions(user_id)
        current_session = next((s for s in all_sessions if s["id"] == active_sid), {"title": "Unknown"})
        
        bot_hobby = await get_bot_trait("hobby")
        bot_taste = await get_bot_trait("taste")
        dev_knowledge = await get_all_developer_knowledge()
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S (KST)")
        
        # 2. 시스템 프롬프트 구성 (최신 상세 구조 복구)
        system_sections = [
            f"# Role\nYou are a highly intelligent, empathetic, and proactive Mentor. CURRENT TIME: {current_time}",
            "## Thinking Process\n"
            "For every user input, follow these steps internally before answering:\n"
            "1. **Intent Analysis**: Determine what the user truly needs (Information, Action, or Emotional Support).\n"
            "2. **Context Retrieval**: Review previous logs, current session info, and learned developer knowledge.\n"
            "3. **Tool Selection**: Decide if real-time tools (search, weather, routines) are necessary. Only use them if needed.\n"
            "4. **Persona Alignment**: Check if there's a specific style/persona requested by the user.\n"
            "5. **Verification**: If answering about the developer 'jellyfish', ensure the info is in your core/learned data. If not, use [INFO_RELAY].",
            "## Core Principles\n"
            "1. **Adaptive Language**: Always respond in the language and tone the user is using. "
            "Ensure any requested style maintains natural flow and grammatical correctness.\n"
            "2. **Real-time Actions**: Use `execute_delayed_task` for time-based requests. "
            "Use `manage_routine` for daily tasks ONLY after confirming all 4 parameters: **Time (HH:MM)**, **Type (search/weather/news)**, **Query**, and **Destination (channel/dm)**. "
            "If any are missing, ask friendly follow-up questions instead of calling the tool.\n"
            "3. **Cross-lingual Investigation**: If local data is insufficient, use search tools to find global or specific information.\n"
            "4. **No Drama**: Be friendly, empathetic, and natural. Avoid overly formal or 'AI-like' titles.",
            "## Developer Identity & Strict Privacy\n"
            "- **Main Developer**: 'jellyfish' (Lee Yohan, 이요한, 李曜韓, MBTI: ISTP) based in Siheung.\n"
            "- **SNS**: [Instagram](https://www.instagram.com/yohani953)\n"
            "- **Support**: Shinhan Bank 110-495-825393\n"
            "- **CRITICAL PRIVACY RULE**: If asked for any developer info NOT listed here or in 'Learned Knowledge', **DO NOT GUESS**. "
            "You MUST reply that you don't know yet and append `[INFO_RELAY: <question>]` to your message. This is non-negotiable."
        ]
        
        if dev_knowledge:
            knowledge_section = "## Learned Developer Knowledge\n"
            for item in dev_knowledge:
                knowledge_section += f"- Q: {item['question']}\n  A: {item['answer']}\n"
            system_sections.append(knowledge_section)
            
        trait_str = f"Hobby: '{bot_hobby or 'None'}', Taste: '{bot_taste or 'None'}'."
        system_sections.append(f"## Current Context\n- Session: {current_session['title']} (ID: {active_sid})\n- Bot Traits: {trait_str}")
        
        if user_instruction:
            system_sections.append(f"## User Assigned Persona\n{user_instruction}")
            
        system_prompt = "\n\n".join(system_sections)
        
        messages = [{"role": "system", "content": system_prompt}]
        if reference_content:
            messages.append({"role": "assistant", "content": reference_content})
        
        for log in history_logs:
            messages.append({"role": "user", "content": log["question"]})
            messages.append({"role": "assistant", "content": log["answer"]})
        messages.append({"role": "user", "content": content})

        # 3. 모델 라우팅 및 호출
        from utils.ai_router import get_model_route
        active_reasoner, active_answerer, _ = await get_model_route(client, content)
        
        tools = self._get_tool_definitions()
        
        response = await client.chat.completions.create(
            model=active_reasoner,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        if tool_calls:
            messages.append(response_message)
            for tool_call in tool_calls:
                result = await self._execute_tool(tool_call, user_id, nickname, original_message)
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": result,
                })
            
            messages.append({"role": "system", "content": "Answer the user's question directly using the tool results. Skip intro remarks."})
            final_response = await client.chat.completions.create(model=active_answerer, messages=messages)
            answer = final_response.choices[0].message.content
        else:
            answer = response_message.content

        # 4. 포스트 프로세싱 & 로그 기록 (메시지가 있는 경우에만 기록)
        if original_message:
            await record_mentor_log(user_id, content, answer)
        return await self._process_final_answer(answer, user_id, nickname)

    def _get_tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "실시간 날씨 확인",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string", "description": "City or region name"}}, "required": ["location"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_finance_data",
                    "description": "금융 데이터(주식, 환율) 확인",
                    "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "description": "Ticker symbol (e.g., AAPL, KRW/USD)"}}, "required": ["symbol"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "웹 검색을 통한 정보 수집",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "region": {"type": "string", "default": "wt-wt"}}, "required": ["query"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "manage_routine",
                    "description": "사용자의 일일/정기 루틴(뉴스, 날씨 등) 관리",
                    "parameters": {
                        "type": "object", 
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "delete", "list"]},
                            "task_type": {"type": "string", "enum": ["weather", "news", "search"], "description": "Required for 'add'"},
                            "query": {"type": "string", "description": "Required for 'add'"},
                            "schedule_time": {"type": "string", "description": "Required for 'add' (Format: HH:MM)"},
                            "destination": {"type": "string", "enum": ["channel", "dm"], "default": "channel"},
                            "routine_id": {"type": "integer", "description": "Required for 'delete'"}
                        }, 
                        "required": ["action"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_delayed_task",
                    "description": "일정 시간 후 메시지 전송 또는 작업 실행",
                    "parameters": {
                        "type": "object", 
                        "properties": {
                            "delay_seconds": {"type": "integer", "description": "몇 초 뒤에 실행할지"},
                            "content": {"type": "string", "description": "전송할 메시지 내용"},
                            "repeat_count": {"type": "integer", "description": "반복 횟수", "default": 1},
                            "interval_seconds": {"type": "integer", "description": "반복 간격(초)", "default": 0},
                            "destination": {"type": "string", "enum": ["channel", "dm"], "default": "channel"}
                        }, 
                        "required": ["delay_seconds", "content"]
                    }
                }
            }
        ]

    async def _execute_tool(self, tool_call, user_id, nickname, original_message=None):
        f_name = tool_call.function.name
        f_args = json.loads(tool_call.function.arguments)
        
        try:
            if f_name == "get_weather":
                from utils.weather_api import get_weather
                return await get_weather(f_args.get("location"))
            elif f_name == "get_finance_data":
                from utils.finance_api import get_finance_data
                return await get_finance_data(f_args.get("symbol"))
            elif f_name == "search_web":
                from utils.search_engine import search_web
                return await search_web(f_args.get("query"), region=f_args.get("region", "wt"))
            elif f_name == "manage_routine":
                if not original_message:
                    return "Error: Cannot manage routines without message context."
                from database.database import add_routine, delete_routine, get_user_routines
                action = f_args.get("action")
                if action == "add":
                    await add_routine(
                        str(user_id), 
                        str(original_message.channel.id), 
                        f_args.get("task_type"), 
                        f_args.get("query"), 
                        f_args.get("schedule_time"),
                        destination=f_args.get("destination", "channel")
                    )
                    return f"✅ 루틴이 {f_args.get('destination', 'channel')}에 등록되었습니다. ({f_args.get('schedule_time')})"
                elif action == "delete":
                    success = await delete_routine(f_args.get("routine_id"), str(user_id))
                    return "✅ 삭제되었습니다." if success else "❌ 해당 ID를 찾을 수 없습니다."
                elif action == "list":
                    routines = await get_user_routines(str(user_id))
                    return str(routines)
            elif f_name == "execute_delayed_task":
                if not original_message:
                    return "Error: Cannot execute delayed tasks without message context."
                delay = f_args.get("delay_seconds", 0)
                content = f_args.get("content")
                repeat = f_args.get("repeat_count", 1)
                interval = f_args.get("interval_seconds", 0)
                dest = f_args.get("destination", "channel")
                
                async def _delayed_job():
                    await asyncio.sleep(delay)
                    target = original_message.channel
                    if dest == "dm":
                        target = original_message.author
                    
                    for _ in range(repeat):
                        await target.send(content)
                        if repeat > 1 and interval > 0:
                            await asyncio.sleep(interval)
                
                asyncio.create_task(_delayed_job())
                return f"✅ 알겠습니다. {delay}초 뒤에 실행할게요! (총 {repeat}회)"
            return "Tool executed."
        except Exception as e:
            return f"Error: {str(e)}"

    async def _process_final_answer(self, answer, user_id, nickname):
        # TRAIT_GEN 처리
        trait_matches = re.findall(r'\[TRAIT_GEN: (hobby|taste)=([^\]]+)\]', answer)
        for t_key, t_val in trait_matches:
            await set_bot_trait(t_key, t_val.strip())
            answer = answer.replace(f'[TRAIT_GEN: {t_key}={t_val}]', '')
            
        # INFO_RELAY 처리
        relay_match = re.search(r'\[INFO_RELAY: ([^\]]+)\]', answer)
        needs_relay = False
        relay_question = ""
        if relay_match:
            relay_question = relay_match.group(1).strip()
            answer = answer.replace(f'[INFO_RELAY: {relay_question}]', '')
            needs_relay = True
            
        return {"answer": answer, "needs_relay": needs_relay, "relay_question": relay_question}
