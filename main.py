import os, uvicorn, aiohttp, asyncio  # , ratelimitqueue
from typing import Any, Optional, Tuple
from pydantic import BaseModel
from fastapi import FastAPI, Response
from rich.console import Console

# --- Constants --- #

app = FastAPI()
console = Console()
# request_queue = ratelimitqueue.RateLimitQueue(calls=10, per=1)

# --- Events --- #


@app.on_event("startup")
async def startup():
    console.log("[API] Starting...")


@app.on_event("shutdown")
async def shutdown():
    console.log("[API] Shutting down...")


# --- Home --- #


class Player(BaseModel):
    id: str
    name: str


async def get_uuid(
    username: str, rerunning: bool = False
) -> dict[str, bool | str | None]:
    """Returns the UUID of a player provided it's a premium player."""
    to_return = {"status": None, "uuid": None, "username": username}
    url = "https://api.mojang.com/users/profiles/minecraft/{}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url.format(username)) as response:
            if response.status == 204:
                to_return["status"] = False
                return to_return
            elif response.status == 200:
                to_return["status"] = True
                data = await response.json()
                to_return["username"] = data["name"]
                to_return["uuid"] = data["id"]
                return to_return
            elif response.status == 429:
                to_return["status"] = False
                if not rerunning:
                    return to_return
                # prevents query from being retried more than twice

                await asyncio.sleep(0.5)
                return await get_uuid(username, rerunning=True)

            to_return["status"] = False
            return to_return


async def check_if_server_premium(players: list[dict[str, str]]) -> Tuple[bool, str | None, list]:  # type: ignore
    """Given a dictionary of usernames to UUIDs, the function returns a boolean or Nonetype of whether or not the server is cracked based on whether or not the UUIDs match with the ones in mojang. To match with function name, response reversed.

    True, None: Server is premium
    False, Reason: Server is cracked
    """
    allowed_letters = "abcdefghijklmnopqrstuvwxyz0123456789_"
    min_length = 3
    max_length = 16

    if len(players) == 0:
        raise IndexError(
            "Players list must contain atleast on element."
        )  # To appease type checker

    # Player = {"username": str, "uuid": unhyphenated uuid4}
    for player in players:
        username = player["username"]

        # If username length doesn't match allowed length
        if len(username) > max_length:
            return False, "length", players
        elif len(username) < min_length:
            return False, "length", players

        # If any non allowed characters are used
        elif len(
            [True for letter in set(username.lower()) if letter in allowed_letters]
        ) != len(set(username.lower())):
            return False, "characters", players
        data = await get_uuid(username)

        # If getting the UUID fails, which can happen if theres no account with the username provided
        if data["status"] == False:
            return False, "failed", players

        # If the UUID is different
        found_uuid = data["uuid"]
        if player["uuid"] != found_uuid:
            return False, "different_uuid", players

        return True, None, players


class Resp(BaseModel):
    status: bool
    message: Optional[str]
    premium: Optional[bool]
    reasons: Optional[list[dict[str, dict[str, bool | str | None]]]]


@app.post("/check_server", response_model=Resp)
async def check_server(players: list[Player]) -> Response | dict[str, bool]:
    # fmt: off
    """
    ## Checks if a server is premium, returns a dictionary.

    #### Args:  
    players (list[Player]): Use the value of the sample field on the ping response. Response['players']['sample'] -> that array is the input for this endpoint.

    #### Returns:  
    - dict[str, str]: Error messages  
    - dict[str, bool]: Normal Responses

    #### Example Response:

    - Failure
            // Input
            []

            // Output
            {
                "status": "err",
                "message": "List must contain atleast one element."
            }                                           

    - Success
            // Input
            [
                {
                    "name":"thinkofdeath",
                    "id":"4566e69f-c907-48ee-8d71-d7ba5aa00d20"
                }
            ]

            // Output
            {
                "status": true,
                "message": null,
                "premium": true,
                "reasons": [{
                    "thinkofdeath": {
                        "premium": true,
                        "reason": null
                    }
                }]
            }

    """
    # fmt: on
    data: list[dict[str, str]] = [player.dict() for player in players]

    if len(data) == 0:
        return Response(
            content={
                "status": False,
                "message": "List must contain atleast one element.",
            },
            status_code=422,
        )

    to_check = [
        {"username": player["name"], "uuid": player["id"].replace("-", "")}
        for player in data
    ]
    to_check_2d = [[data] for data in to_check]
    gathered = await asyncio.gather(
        *[check_if_server_premium(to_check_q) for to_check_q in to_check_2d]
    )
    to_return = {
        "status": True,
        "reasons": [
            {g[2][0]["username"]: {"premium": g[0], "reason": g[1]}} for g in gathered
        ],
    }
    reason_bools = [bruh['premium'] for bruh in [list(reason.values())[0] for reason in to_return['reasons']]]
    if False in reason_bools:
        to_return['premium'] = False
    else:
        to_return['premium'] = True
    return to_return


# --- Running --- #

if __name__ == "__main__":
    uvicorn.run(
        f"{os.path.basename(__file__).replace('.py', '')}:app",
        host="0.0.0.0",
        port=80,
        reload=True,
    )
