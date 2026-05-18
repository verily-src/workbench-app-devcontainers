from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")

response = client.chat.completions.create(
    model="gemma4:26b",
    messages=[{"role": "user", "content": "Hello, who are you?"}],
    max_tokens=100,
)
print(response.choices[0].message.content)
