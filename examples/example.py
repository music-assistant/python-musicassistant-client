"""Some simple tests/examples for the Music Assistant client."""

import asyncio
import logging
import sys

from musicassistant_client import MusicAssistant, async_get_token

LOGGER = logging.getLogger()


def global_exception_handler(loop, context) -> None:
    """Global exception handler."""
    LOGGER.exception(
        "Caught exception: %s", context.get("exception", context["message"])
    )
    loop.default_exception_handler(context)


if __name__ == "__main__":

    logformat = logging.Formatter(
        "%(asctime)-15s %(levelname)-5s %(name)s.%(module)s -- %(message)s"
    )
    consolehandler = logging.StreamHandler()
    consolehandler.setFormatter(logformat)
    LOGGER.addHandler(consolehandler)
    LOGGER.setLevel(logging.DEBUG)

    if len(sys.argv) < 3:
        LOGGER.error("usage: example.py <host> <username> <password>")
        sys.exit()

    host = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(global_exception_handler)

    async def mass_event(event, event_details):
        """Handle callback for received events."""
        LOGGER.info("received event %s --> %s\n", event, event_details)

    async def run():
        """Handle async code execution."""
        # retrieve token
        token = await async_get_token(host, username, password)
        # connect to server and issue some commands
        async with MusicAssistant(host, token, loop=loop) as mass:
            # register event callback
            mass.register_event_callback(mass_event)
            # get data from a few endpoints
            players = await mass.async_get_players()
            LOGGER.info(
                "There are %s players registered in Music Assistant", len(players)
            )
            artists = await mass.async_get_library_artists()
            LOGGER.info(
                "There are %s artists registered in Music Assistant", len(artists)
            )
            albums = await mass.async_get_library_albums()
            LOGGER.info(
                "There are %s albums registered in Music Assistant", len(albums)
            )
            tracks = await mass.async_get_library_tracks()
            LOGGER.info(
                "There are %s tracks registered in Music Assistant", len(tracks)
            )
            playlists = await mass.async_get_library_playlists()
            LOGGER.info(
                "There are %s playlists registered in Music Assistant", len(playlists)
            )

            # register player control
            async def player_control_command(new_state):
                LOGGER.info("Player control, new state requested: %s", new_state)
                # report back new state
                await mass.async_update_player_control("example", new_state)

            await mass.async_register_player_control(
                0, "example", "example", "Example", False, player_control_command
            )

            # just wait a bit and receive events
            await asyncio.sleep(600)
        loop.stop()

    try:
        loop.create_task(run())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
        loop.close()
