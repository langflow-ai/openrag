messages = [{"role": "system", "content": "You are a helpful assistant. Always use the search_tools to answer questions."}]

# Async version for web server
async def async_chat(async_client, prompt: str, model: str = "gpt-4.1-mini", previous_response_id: str = None) -> str:
    global messages
    messages += [{"role": "user", "content": prompt}]
    response = await async_client.responses.create(
        model=model,
        input=prompt,
        previous_response_id=previous_response_id,
    )

    response_id = response.id
    response_text = response.output_text
    print(f"user ==> {prompt}")
    print(f"agent ==> {response_text}")
    return response_text