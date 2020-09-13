"""Some simple tests/examples for the Music Assistant client."""

import asyncio
import logging
import sys

from musicassistant_client import (
    EVENT_PLAYER_ADDED,
    EVENT_PLAYER_CHANGED,
    EVENT_QUEUE_UPDATED,
    MusicAssistant,
)

LOGGER = logging.getLogger()

if __name__ == "__main__":

    logformat = logging.Formatter(
        "%(asctime)-15s %(levelname)-5s %(name)s.%(module)s -- %(message)s"
    )
    consolehandler = logging.StreamHandler()
    consolehandler.setFormatter(logformat)
    LOGGER.addHandler(consolehandler)
    LOGGER.setLevel(logging.DEBUG)

    if len(sys.argv) < 4:
        LOGGER.error("usage: example.py <url> <username> <password>")
        sys.exit()

    url = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]
    loop = asyncio.get_event_loop()
    mass = MusicAssistant(url, username, password)

    async def mass_event(event, event_details):
        """Handle callback for received events."""
        LOGGER.info("received event %s --> %s\n", event, event_details)

    mass.register_event_callback(
        mass_event, [EVENT_PLAYER_ADDED, EVENT_PLAYER_CHANGED, EVENT_QUEUE_UPDATED]
    )

    async def run():
        """Handle async code execution."""
        await mass.async_connect()
        players = await mass.async_get_players()
        LOGGER.info("There are %s players registered in Music Assistant", len(players))
        artists = await mass.async_get_library_artists()
        LOGGER.info("There are %s artists registered in Music Assistant", len(artists))
        albums = await mass.async_get_library_albums()
        LOGGER.info("There are %s albums registered in Music Assistant", len(albums))
        tracks = await mass.async_get_library_tracks()
        LOGGER.info("There are %s tracks registered in Music Assistant", len(tracks))
        playlists = await mass.async_get_library_tracks()
        LOGGER.info(
            "There are %s playlists registered in Music Assistant", len(playlists)
        )
        await asyncio.sleep(10)
        await mass.async_close()
        loop.stop()

    try:
        loop.create_task(run())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
        loop.close()
