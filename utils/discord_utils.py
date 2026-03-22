import discord
from typing import Union

async def split_send(target: Union[discord.abc.Messageable, discord.User, discord.Member, discord.TextChannel], content: str, chunk_size: int = 1900):
    """
    Splits a long message into chunks and sends them to the target.
    Priority is given to splitting by newlines to preserve formatting.
    """
    if not content:
        return

    if len(content) <= chunk_size:
        await target.send(content)
        return

    # Split into parts
    parts = []
    remaining = content.strip()
    
    while remaining:
        if len(remaining) <= chunk_size:
            parts.append(remaining)
            break
        
        # Find best cut index (newline is best)
        cut_idx = remaining.rfind('\n', 0, chunk_size)
        if cut_idx == -1:
            # No newline, split at chunk_size
            cut_idx = chunk_size
            
        parts.append(remaining[:cut_idx].strip())
        remaining = remaining[cut_idx:].strip()

    for part in parts:
        if part:
            await target.send(part)
