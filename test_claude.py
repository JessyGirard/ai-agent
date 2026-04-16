import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv


def main():
    load_dotenv()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "What is the capital of France?"},
        ],
    )
    print(response.content[0].text)


if __name__ == "__main__":
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        print("Skipping live API test. Set RUN_LIVE_API_TESTS=1 to run.")
        sys.exit(0)
    main()
