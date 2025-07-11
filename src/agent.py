import asyncio

from agentd.patch import patch_openai_with_mcp

messages = [{"role": "system", "content": "You are a helpful assistant. use your tools to answer questions."}]

# Async version for web server
async def async_chat(async_client, prompt: str) -> str:
    global messages
    messages += [{"role": "user", "content": prompt}]
    response = await async_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        mcp_strict=True
    )

    response_text = response.choices[0].message.content
    print(f"user ==> {prompt}")
    print(f"agent ==> {response_text}")
    return response_text

if __name__ == "__main__":
    asyncio.run(async_chat("What pods are there?"))