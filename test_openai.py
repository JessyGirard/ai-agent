import os
import sys

from dotenv import load_dotenv


def main():
    from openai import OpenAI

    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-4.1-mini",
        input="Say hello in one short sentence.",
    )
    print(response.output_text)


if __name__ == "__main__":
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        print("Skipping live API test. Set RUN_LIVE_API_TESTS=1 to run.")
        sys.exit(0)
    main()
