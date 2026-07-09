# Ani Zeo Changelog

## Version 0.1
- Created Telegram Bot
- Added /start

## Version 0.2
- Added /search

## Version 0.3
- Added /top

## Version 0.4
- Added /random

## Version 0.5
- Added /similar

## Version 0.6
- Added /order

## Version 0.7
- Added /help

## Version 0.8
- Added /genre command
- Browse top anime by genre using the Jikan API
- Supports 20 genres: action, adventure, comedy, drama, fantasy, horror, mystery, romance, sci-fi, slice of life, sports, supernatural, thriller, mecha, music, psychological, historical, isekai, shounen, shoujo
- Fixed IndentationError in /similar exception handler
- Fixed MarkdownV2 formatting crash in /genre caused by unescaped dynamic anime titles

## Version 0.9
- Added /season command — top airing anime this season with today's date (DD MMM YYYY)
- Added /airing command — anime airing today by day schedule via Jikan API
- Fixed /season not responding after code change (missing workflow restart)

## Version 1.0
- Added /character <anime> — top 5 main characters with name and role
- Added /studio <anime> — studio name, type, and anime count via Jikan producers API
- Improved /help — grouped by category (Search, Rankings, Seasonal, Discovery) with cleaner layout
- Switched /help to plain text to prevent MarkdownV2 parse errors on special characters
- All 12 commands stable and tested: /start, /help, /search, /similar, /character, /studio, /top, /genre, /season, /airing, /random, /order

## Version 2.0
- Integrated AniList GraphQL API alongside Jikan for richer data
- Added interactive Reply Keyboard menu (10 quick-access buttons on /start)
- /search now sends anime poster image + enhanced details (Japanese/English/romaji titles, rank, popularity, season, source material, duration, streaming platforms)
- Streaming platform detection from AniList external links (Crunchyroll, Netflix, Hulu, Prime Video, etc.) — hidden when unavailable
- Added /trending — top trending anime right now via AniList
- Added /news — latest airing anime updates with next episode countdown
- Added /trailer <anime> — official YouTube trailer link via AniList
- Added /compare <anime1> vs <anime2> — side-by-side score, episodes, status, members, studio, genre comparison
- Added /schedule <day> — airing anime for any day of the week
- Added /quiz — 15-question anime trivia quiz with inline answer buttons
- Added /favorite add/remove <anime> — save up to 20 personal favourites (persisted to JSON)
- Added /favorites — view your saved anime list
- /character upgraded to AniList (includes native Japanese name)
- /studio upgraded to AniList (type, favourites count, site URL)
- /help redesigned with version number, command count, and full category grouping
- All 20 commands stable and tested

## Version 2.1
- Added /beginner — comprehensive guide for newcomers to anime, categorised by genre
- Added /starterpack — curated 10 essential anime to start with, with descriptions
- Added /recommend <anime|genre> — smart recommendations using Jikan's recommendation engine
- Expanded /order database from 20 → 29 franchises (added Gundam, Higurashi, Pokémon, Digimon, No Game No Life, Log Horizon, Re:Creators, Made in Abyss, Violet Evergarden)
- Expanded WATCH_ORDER_ALIASES from ~40 → ~80 shortcuts (jjk, mha, fmab, opm, pokémon, pikachu, abyss, violet, etc.)
- Genre deduplication via _franchise_key() prevents duplicate franchise entries in all genre/recommend results

## Version 3.0 — Ultimate Anime Companion
Released: 2026-06-08

### NEW: Watchlist System
- /watchlist — view your full watchlist across all statuses
- /watchlist add <anime> [watching|completed|planned|dropped] — add anime to a list (default: planned)
- /watchlist remove <anime> — remove anime from any list
- /watchlist watching / completed / planned / dropped — view specific category
- Persisted permanently per Telegram user ID in watchlist.json

### NEW: User Profiles & Stats
- /profile — displays your personal anime profile card
- /stats — alias for /profile
- Tracks: join date, anime searched, manga searched, genres used, most used commands, favourites count, activity score, watchlist breakdown
- Profile data persisted in profiles.json, auto-created on first interaction

### NEW: Manga System (4 commands)
- /manga <title> — full manga details: title, score, rank, chapters, volumes, status, author, magazine, genres, synopsis; sends cover image via Jikan API
- /topmanga — top 10 manga of all time with score and chapter count
- /randommanga — random manga pick with cover image
- /mangagenre <genre> — top manga by genre (supports 18 genres)

### NEW: Dub Availability
- /dub <anime> — shows all dubbed languages available for an anime using AniList voice actor data
- Detects: Japanese, English, Spanish, Portuguese, French, German, Italian, Korean, Chinese
- Shows streaming platforms where available
- Notes regional dub availability (Hindi/Tamil/Telugu) for platforms not in AniList data

### NEW: Upcoming Anime
- /upcoming — top 10 most anticipated upcoming anime sorted by member tracking count
- Shows: studio, episode count, season/year, tracking numbers via Jikan upcoming season API

### ENHANCED: /character
- Now shows voice actors alongside characters
- Japanese VA (🇯🇵) and English dub VA (🇬🇧) per character
- Shows character gender where available
- Uses expanded AniList query with voiceActors field

### ENHANCED: /genre
- Now returns 10 results instead of 5
- Randomises from pages 1–4 of the top 100 — fresh results every time
- Franchise deduplication still prevents repeated series
- Profile tracking: records genre searches to user profile

### ENHANCED: /search
- Now includes prequel (⬅) and sequel (➡) relations in output
- Uses expanded AniList query with relations edges
- Profile tracking: increments anime_searched counter on each use

### ENHANCED: /recommend
- Genre mode now returns 10 deduplicated picks (was 5)
- Anime mode now returns 10 recommendations (was 5)
- Supports "anime like X" and "similar to X" natural language patterns
  - Example: /recommend anime like death note

### ENHANCED: /order
- /order with no arguments now lists all supported franchises
- Not-found message now says "watch from Episode 1" instead of generic error
- Smart suggestions: shows similar franchise names on no match
- Franchise count: 37 total with 80+ shortcuts/aliases

### Technical
- Added WATCHLIST_FILE and PROFILES_FILE path constants
- update_profile() helper auto-initialises user records on first use
- All new data files use per-user dict keyed by Telegram user ID string
- Backward-compatible: all 23 v2.0 commands continue working unchanged
- Total commands: 33
