**Basically a car GPS, but for Azeroth.** Tell it where you want to go and it draws the way there along the actual roads and trails, with turn-by-turn directions, distances and an ETA.

_Want the full rundown of every feature, option and command? Because it's a lot! It's all in the **[AzerothGPS wiki](https://github.com/AzerothGPS/AzerothGPS/wiki)**._

![Double-clicking Goldshire and a spot nearby, confirming, then following the route with the direction arrow](https://github.com/user-attachments/assets/81709111-9f3d-43d0-af64-d24932cbcadb)

_Double-click where you want to go, confirm, and follow the arrow._

## It knows the terrain

No more running straight at a mountain and wondering why you're stuck. When cliffs or ridges are in the way, the route goes around them and in through the pass. It sticks to the roads where that makes sense, and when you're off the road it joins up where you're headed, not back at the closest bit behind you. Take your own shortcut and it just adjusts. Got a bunch of places to hit? Add as many stops as you like and it sorts them into the fastest order.

![A route around a mountain ridge and in through the pass to a walled-off valley](https://github.com/user-attachments/assets/404db654-3b13-4a3f-86c6-c693e3181844)

![A three-stop trip in Mulgore along the roads, with the direction arrow above the map](https://github.com/user-attachments/assets/9f86bb86-8e44-48eb-9a78-725811e2667c)

## Your quest log, routed

Quest areas show up on the map just like on your minimap. One click and it routes you through your whole quest log: every objective and every turn-in, in the fastest order. A stop in a quest area waits until you've finished that quest's objectives, then the route moves on.

![In Tirisfal: the Quest Route button, the route through the quest log's objectives and turn-ins](https://github.com/user-attachments/assets/b2d377c4-7d35-4f0c-a86e-b83bfc3e105e)

## Stays out of your way

*   **Size and opacity:** make it as big or as see-through as you want. A bigger map shows more of the world, not just the same bit blown up.
*   **Moving and fighting:** it can fade while you run, go click-through, or dim or hide in combat.
*   **Show/hide key:** bind whatever key you like.
*   **Older PC?** Options → Performance lets you turn down how often the map redraws and the route gets recalculated. There's a one-click low-end preset, and it shows you live how much time AzerothGPS is actually taking.

## Farming, on every character

Every herb and ore node you gather, hover over on the minimap, or right-click without the profession ("Requires Herbalism") gets remembered across all your characters. Draw around a spot and it routes a loop through every node in it.

![On Zephras Isle: the herb and ore buttons, Draw a Farming Area, a loop drawn round the nodes, the route through them](https://github.com/user-attachments/assets/09e4ea32-aa55-4921-8526-1164ee2e7709)

## Spot a mistake? Fix it

If a route misses a trail or walks you into a wall, draw the fix right on the map and routes use it straight away. Send it by following directions in "Help improve" menu (`/reload`, then **Copy Map Data…**) and if it checks out, it ships in the next version for everybody.

![Road tools in Silverpine: circling a road to erase it, drawing the real one, the route taking it](https://github.com/user-attachments/assets/f6d11814-0bcb-4ba4-bba6-59afa1f9f3ba)

## Also in there

*   **Every way to get around:** flight paths (plus a detour to pick up ones you pass but haven't learned), boats and zeppelins with countdowns to their next arrival, the Deeprun Tram, your hearthstone, class teleports and engineer teleporters. You can hearth or teleport with one click right from the directions. Don't fancy a certain flight or boat? Right-click it and the route skips it. If that leaves no way there, it tells you and offers to put it back.
*   **Cities and caves:** every capital's streets (stairs called out), Undercity's floors, 353 caves and mines, and the lifts: Thunder Bluff's, Undercity's, the Great Lift down to Thousand Needles and Freewind Post's.
*   **Dungeons and raids:** floor-by-floor maps, bosses in order, and a boss route. Dungeons with wings get an icon per wing, each with its own bosses and route: Scarlet Monastery's Graveyard, Library, Armory and Cathedral, Dire Maul's East, West and North, Stratholme's two gates, Maraudon's Orange and Purple.
*   **Keeping you alive:** routes steer around the other faction's towns and zones way above your level. If the only way there runs through one, it asks before it shows you that route.
*   **Your own pins:** Shift-click the map to drop a pin with any icon from the game and a name. Double-click it later to route there, even on the right floor of a dungeon.
*   **Your group on the map:** party and raid members show up as round class icons in their class color. They don't need the addon.
*   **Turn-by-turn directions** with ETAs at your actual speed, on foot, mounted or in travel form.
*   **TomTom `/way`** import, and you can share routes with friends.
*   **Display only:** it never moves your character, clicks anything for you or automates anything. It just shows you the way.

## Getting started

1.  The map sits at the bottom of your screen (type `/agps show` if it's hidden).
2.  **Double-click the map** to add a stop, then click **Confirm Route** (or just wait 5 seconds).
3.  Follow the line on the map, or the arrow.
4.  Using flight paths? Open the flight map at any flight master once so it knows which ones you have.

## Come say hi

*   **Discord:** questions, ideas and news on the **[AzerothGPS Discord](https://discord.gg/gktYHzs2c)**. Come hang out.
*   **Bugs and bad routes:** open an issue on [GitHub](https://github.com/AzerothGPS/AzerothGPS/issues) or post in the Discord. Include the zone and your start and destination coordinates (they're at the bottom of the map).
*   **Map fixes:** draw them with the road or wall tools, type `/reload` (that saves every edit), then **Copy Map Data…** (Options → Help improve) and paste it into a [Road data issue](https://github.com/AzerothGPS/AzerothGPS/issues/new?template=road-data.yml) or the Discord.

_AzerothGPS is a fan-made addon and is not affiliated with or endorsed by Blizzard Entertainment. World of Warcraft and Azeroth are trademarks of Blizzard Entertainment, Inc._