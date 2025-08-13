from livekit.agents import Agent


class AvatarEngine(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are a helpful voice AI assistant.")
