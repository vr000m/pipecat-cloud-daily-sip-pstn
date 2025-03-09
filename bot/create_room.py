# create_room.py

endpoint = "https://api.pipecat.daily.co/v1/public/{service}/start"
agent_name = "my-pstn-agent"
daily_api_key = "pk_2f4e6e3b-2816-4cf3-979c-2974eb6c501b"

async with aiohttp.ClientSession() as session:
    response = await session.post(
        f"{endpoint.format(service=agent_name)}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "createDailyRoom": True,  # Creates a Daily room
            "body": {"custom": "data"},  # Data to pass to your agent
        },
    )

# from pipecatcloud import Session, SessionParams
# from pipecatcloud.exception import AgentStartError


# async def create_session():
#     print("Creating a session with Daily transport")
#     try:
#         # Create a session with Daily integration
#         session = Session(
#             agent_name="my-pstn-agent",
#             api_key=daily_api_key,  # Your public API key
#             params=SessionParams(
#                 use_daily=True,  # Creates a Daily room
#                 data={"dialin_settings": "hello"},  # Optional data to pass to your agent
#             ),
#         )
#         response = await session.start()
#         # Print confirmation and session information
#         print("Session created successfully!")
#         # print(f"Session object: {session}")

#         # Add these lines to see specific properties
#         print(f"Daily Room URL: {session.dailyRoom}")
#         print(f"Daily Token: {session.dailyToken}")

#         # Process the response
#         print("Session started successfully")
#         if "dailyRoom" in response:
#             print(f"Daily room: {response['dailyRoom']}")

#     except AgentStartError as e:
#         print(f"Error starting agent: {e}")
#     except Exception as e:
#         print(f"Unexpected error: {e}")


# # Run the async function
# if __name__ == "__main__":
#     asyncio.run(create_session())
