import os
import json
from typing import AsyncGenerator, List, Dict, Any
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()


class DeepSeekService:
    """DeepSeek API 服务封装"""
    
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment variables")
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        self.model = "deepseek-chat"  # 固定使用 deepseek-chat
    
    async def stream_chat(
        self, 
        messages: List[Dict[str, str]], 
        thinking_enabled: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式聊天接口
        
        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}, ...]
            thinking_enabled: 是否开启思考模式
        
        Yields:
            {"type": "reasoning", "data": "..."} - 思考内容
            {"type": "content", "data": "..."} - 回答内容
            {"type": "done", "reasoning": "...", "content": "..."} - 完成
            {"type": "error", "error": "..."} - 错误
        """
        try:
            # 构建请求参数
            kwargs = {
                "model": self.model,
                "messages": messages,
                "stream": True,
            }
            
            # 如果开启思考模式，添加 thinking 参数
            if thinking_enabled:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            
            response = await self.client.chat.completions.create(**kwargs)
            
            full_reasoning = ""
            full_content = ""
            
            async for chunk in response:
                delta = chunk.choices[0].delta
                
                # 处理思考内容
                reasoning_chunk = getattr(delta, 'reasoning_content', None)
                if reasoning_chunk:
                    full_reasoning += reasoning_chunk
                    yield {"type": "reasoning", "data": reasoning_chunk}
                
                # 处理回答内容
                content_chunk = getattr(delta, 'content', None)
                if content_chunk:
                    full_content += content_chunk
                    yield {"type": "content", "data": content_chunk}
            
            # 完成信号
            yield {
                "type": "done", 
                "reasoning": full_reasoning if full_reasoning else None,
                "content": full_content
            }
            
        except Exception as e:
            yield {"type": "error", "error": str(e)}


# 全局服务实例
deepseek_service = DeepSeekService()
