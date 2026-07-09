import os
import json
import random
import re
import requests
from datetime import datetime
from pathlib import Path
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from ai.message_handler import handle_text_message
from ai.router import AIRouter

# Shared router instance — re-used across all /ai requests.
_ai_router = AIRouter()

# ── Config ─────────────────────────────────────────────────────────────────

ANILIST_URL = "https://graphql.anilist.co"
FAVORITES_FILE  = Path("favorites.json")
WATCHLIST_FILE  = Path("watchlist.json")
PROFILES_FILE   = Path("profiles.json")
EXCLUDED_GENRES = {"hentai", "erotica"}

STREAMING_SITES = {
    "Crunchyroll", "Netflix", "Amazon Prime Video", "Prime Video",
    "Disney Plus", "Disney+", "Hulu", "HIDIVE", "Muse Asia",
    "Ani-One", "Ani-One Asia", "Funimation", "VRV", "Bilibili",
}

STATUS_MAP = {
    "FINISHED": "Finished",
    "RELEASING": "Currently Airing",
    "NOT_YET_RELEASED": "Upcoming",
    "CANCELLED": "Cancelled",
    "HIATUS": "On Hiatus",
}

SOURCE_MAP = {
    "MANGA": "Manga", "LIGHT_NOVEL": "Light Novel",
    "VISUAL_NOVEL": "Visual Novel", "VIDEO_GAME": "Video Game",
    "ORIGINAL": "Original", "NOVEL": "Novel", "ANIME": "Anime",
    "WEB_MANGA": "Web Manga", "BOOK": "Book", "COMIC": "Comic",
    "ONE_SHOT": "One-Shot", "OTHER": "Other",
}

GENRE_MAP = {
    "action": 1, "adventure": 2, "comedy": 4, "drama": 8,
    "fantasy": 10, "horror": 14, "mystery": 7, "romance": 22,
    "sci-fi": 24, "scifi": 24, "science fiction": 24,
    "slice of life": 36, "sports": 30, "supernatural": 37,
    "thriller": 41, "mecha": 18, "music": 19, "psychological": 40,
    "historical": 13, "isekai": 62, "shounen": 27, "shoujo": 25,
}

WATCH_ORDERS = {
    "attack on titan": {
        "title": "Attack on Titan (Shingeki no Kyojin)",
        "order": [
            "Shingeki no Kyojin Season 1",
            "Shingeki no Kyojin Season 2",
            "Shingeki no Kyojin Season 3 Part 1",
            "Shingeki no Kyojin Season 3 Part 2",
            "Shingeki no Kyojin: The Final Season Part 1",
            "Shingeki no Kyojin: The Final Season Part 2",
            "Shingeki no Kyojin: The Final Chapters Part 1 & 2",
        ],
    },
    "demon slayer": {
        "title": "Demon Slayer (Kimetsu no Yaiba)",
        "order": [
            "Kimetsu no Yaiba Season 1",
            "Kimetsu no Yaiba the Movie: Mugen Train",
            "Kimetsu no Yaiba: Entertainment District Arc (Season 2)",
            "Kimetsu no Yaiba: Swordsmith Village Arc (Season 3)",
            "Kimetsu no Yaiba: Hashira Training Arc (Season 4)",
        ],
    },
    "jujutsu kaisen": {
        "title": "Jujutsu Kaisen",
        "order": [
            "Jujutsu Kaisen 0 (Movie — prequel, watch first)",
            "Jujutsu Kaisen Season 1",
            "Jujutsu Kaisen Season 2 (Gojo Past + Shibuya Incident)",
            "Jujutsu Kaisen Season 3 (Culling Game Arc)",
        ],
    },
    "chainsaw man": {
        "title": "Chainsaw Man",
        "order": [
            "Chainsaw Man Season 1 (MAPPA, 2022)",
            "Chainsaw Man Movie: Reze-hen (2025, canon)",
            "Tip: Read the manga for content beyond the anime",
        ],
    },
    "my hero academia": {
        "title": "My Hero Academia (Boku no Hero Academia)",
        "order": [
            "Boku no Hero Academia Season 1",
            "Boku no Hero Academia Season 2",
            "Boku no Hero Academia: Two Heroes (Movie, optional)",
            "Boku no Hero Academia Season 3",
            "Boku no Hero Academia Season 4",
            "Boku no Hero Academia: Heroes Rising (Movie, optional)",
            "Boku no Hero Academia Season 5",
            "Boku no Hero Academia Season 6",
            "Boku no Hero Academia Season 7",
        ],
    },
    "dragon ball": {
        "title": "Dragon Ball Series",
        "order": [
            "Dragon Ball (Original — optional, sets the foundation)",
            "Dragon Ball Z — The iconic classic",
            "Dragon Ball Z Kai — Condensed DBZ, no filler (alternative to DBZ)",
            "Dragon Ball GT (Non-canon, optional)",
            "Dragon Ball Super",
            "Dragon Ball Super: Broly (Movie, canon)",
            "Dragon Ball Super: Super Hero (Movie, canon)",
        ],
    },
    "naruto": {
        "title": "Naruto Series",
        "order": [
            "Naruto (Original — use a filler guide)",
            "Naruto: Shippuden (500 eps — use a filler guide)",
            "The Last: Naruto the Movie (Canon)",
            "Boruto: Naruto Next Generations (Sequel series)",
        ],
    },
    "one piece": {
        "title": "One Piece",
        "order": [
            "One Piece (1000+ episodes — use a filler guide)",
            "One Piece Film: Z (Standalone, optional)",
            "One Piece Film: Gold (Standalone, optional)",
            "One Piece Film: Red (2022, some canon elements)",
            "Tip: Manga and anime are both legendary — either works",
        ],
    },
    "bleach": {
        "title": "Bleach",
        "order": [
            "Bleach (eps 1–366 — use a filler guide)",
            "Bleach: Thousand-Year Blood War (Final arc, 2022–2024)",
            "Tip: TYBW is the best arc — worth watching standalone",
        ],
    },
    "hunter x hunter": {
        "title": "Hunter x Hunter",
        "order": [
            "Hunter x Hunter (2011) — Skip the 1999 version",
            "Hunter x Hunter: The Last Mission (Movie, non-canon, optional)",
            "Tip: Power through early arcs — Chimera Ant arc is legendary",
        ],
    },
    "fullmetal alchemist": {
        "title": "Fullmetal Alchemist",
        "order": [
            "RECOMMENDED: Fullmetal Alchemist: Brotherhood (follows the manga)",
            "",
            "Or watch the original route:",
            "Fullmetal Alchemist (2003 — diverges from manga after ep 25)",
            "Fullmetal Alchemist: Conqueror of Shamballa (2003 ending movie)",
            "Then: Fullmetal Alchemist: Brotherhood",
        ],
    },
    "sword art online": {
        "title": "Sword Art Online",
        "order": [
            "Sword Art Online (SAO arc + ALO arc)",
            "Sword Art Online II (GGO + Calibur + Mother's Rosario)",
            "Sword Art Online: Ordinal Scale (Movie, canon)",
            "Sword Art Online: Alicization",
            "Sword Art Online: Alicization — War of Underworld",
            "SAO Progressive: Aria of a Starless Night (Movie, canon)",
            "SAO Progressive: Scherzo of Deep Night (Movie, canon)",
        ],
    },
    "re:zero": {
        "title": "Re:Zero",
        "order": [
            "Re:Zero Season 1",
            "Re:Zero: Memory Snow (OVA, optional — after S1)",
            "Re:Zero: Frozen Bond (OVA, optional — before S2)",
            "Re:Zero Season 2 Part 1",
            "Re:Zero Season 2 Part 2",
            "Re:Zero Season 3",
        ],
    },
    "evangelion": {
        "title": "Neon Genesis Evangelion",
        "order": [
            "Neon Genesis Evangelion (TV, 26 eps)",
            "The End of Evangelion (Movie — alternate ending, MUST WATCH)",
            "Death & Rebirth (optional recap)",
            "— Rebuild of Evangelion (alternate retelling) —",
            "Evangelion 1.0: You Are (Not) Alone",
            "Evangelion 2.0: You Can (Not) Advance",
            "Evangelion 3.0: You Can (Not) Redo",
            "Evangelion 3.0+1.0: Thrice Upon a Time",
        ],
    },
    "code geass": {
        "title": "Code Geass",
        "order": [
            "Code Geass: Lelouch of the Rebellion Season 1",
            "Code Geass: Lelouch of the Rebellion R2",
            "Code Geass: Akito the Exiled (OVA, optional spinoff)",
            "Code Geass: Lelouch of the Re;surrection (Movie sequel, 2019)",
        ],
    },
    "jojo": {
        "title": "JoJo's Bizarre Adventure",
        "order": [
            "Part 1: Phantom Blood (eps 1–9)",
            "Part 2: Battle Tendency (eps 10–26)",
            "Part 3: Stardust Crusaders (Season 2, 48 eps)",
            "Part 4: Diamond is Unbreakable (Season 3, 39 eps)",
            "Part 5: Golden Wind (Season 4, 39 eps)",
            "Part 6: Stone Ocean (Netflix, 38 eps)",
            "Part 7: Steel Ball Run (in production)",
        ],
    },
    "steins;gate": {
        "title": "Steins;Gate",
        "order": [
            "Steins;Gate (TV, 24 eps) — Start here",
            "Steins;Gate: Oukoubakko no Protonovax (OVA, optional)",
            "Steins;Gate 0 (Alternate route — watch after the original)",
            "Tip: Steins;Gate 0 requires the original to make sense",
        ],
    },
    "fate": {
        "title": "Fate Series",
        "order": [
            "Fate/Zero Season 1 & 2 — Best starting point",
            "Fate/stay night: Unlimited Blade Works (TV) Season 1 & 2",
            "Fate/stay night: Heaven's Feel I. presage flower (Movie)",
            "Fate/stay night: Heaven's Feel II. lost butterfly (Movie)",
            "Fate/stay night: Heaven's Feel III. spring song (Movie)",
            "Fate/Grand Order: Babylonia (Spinoff, optional)",
            "Fate/Apocrypha (Alternate universe, optional)",
            "Lord El-Melloi II's Case Files (Spinoff, optional)",
        ],
    },
    "monogatari": {
        "title": "Monogatari Series",
        "order": [
            "Bakemonogatari",
            "Kizumonogatari I, II, III (Movies)",
            "Nisemonogatari",
            "Nekomonogatari: Kuro",
            "Monogatari Series: Second Season",
            "Hanamonogatari",
            "Tsukimonogatari",
            "Owarimonogatari Season 1",
            "Koyomimonogatari",
            "Owarimonogatari Season 2",
            "Zoku Owarimonogatari",
            "Monogatari Series: Off & Monster Season",
        ],
    },
    "toaru": {
        "title": "Toaru Series (A Certain...)",
        "order": [
            "Toaru Majutsu no Index Season 1",
            "Toaru Kagaku no Railgun Season 1",
            "Toaru Majutsu no Index II Season 2",
            "Toaru Kagaku no Railgun S Season 2",
            "Toaru Majutsu no Index III Season 3",
            "Toaru Kagaku no Railgun T Season 3",
            "Toaru Kagaku no Accelerator (Spinoff, optional)",
        ],
    },
    "overlord": {
        "title": "Overlord",
        "order": [
            "Overlord Season 1",
            "Overlord Season 2",
            "Overlord Season 3",
            "Overlord Season 4",
            "Note: Recap movies (The Undead King / Dark Warrior) cover S1 only",
        ],
    },
    "konosuba": {
        "title": "KonoSuba",
        "order": [
            "KonoSuba Season 1",
            "KonoSuba Season 2",
            "KonoSuba: Legend of Crimson (Movie)",
            "KonoSuba: An Explosion on This Wonderful World! (Megumin spinoff)",
            "KonoSuba Season 3",
        ],
    },
    "tensura": {
        "title": "That Time I Got Reincarnated as a Slime",
        "order": [
            "Tensei shitara Slime Datta Ken Season 1",
            "Tensei shitara Slime Datta Ken Season 2 Part 1",
            "Tensei shitara Slime Datta Ken Season 2 Part 2",
            "Tensura Movie: Scarlet Bond (canon)",
            "Tensei shitara Slime Datta Ken Season 3",
        ],
    },
    "danmachi": {
        "title": "DanMachi (Is It Wrong to Pick Up Girls in a Dungeon?)",
        "order": [
            "DanMachi Season 1",
            "Sword Oratoria (Aiz spinoff — optional, after S1)",
            "DanMachi Season 2",
            "DanMachi: Arrow of the Orion (Movie, optional)",
            "DanMachi Season 3",
            "DanMachi Season 4 Part 1 & Part 2",
            "DanMachi Season 5",
        ],
    },
    "tokyo ghoul": {
        "title": "Tokyo Ghoul",
        "order": [
            "Tokyo Ghoul Season 1",
            "Tokyo Ghoul Root A (Season 2 — diverges from manga)",
            "Tokyo Ghoul:re Season 3",
            "Tokyo Ghoul:re Part 2 Season 4",
            "Tip: The manga tells a much better story — highly recommended",
        ],
    },
    "fairy tail": {
        "title": "Fairy Tail",
        "order": [
            "Fairy Tail (eps 1–175, use filler guide)",
            "Fairy Tail: Phoenix Priestess (Movie, optional)",
            "Fairy Tail (eps 176–277, use filler guide)",
            "Fairy Tail: Dragon Cry (Movie, optional)",
            "Fairy Tail: Final Series (eps 278–328)",
            "Fairy Tail: 100 Years Quest (2024 continuation)",
        ],
    },
    "one punch man": {
        "title": "One Punch Man",
        "order": [
            "One Punch Man Season 1 (Madhouse — exceptional quality)",
            "One Punch Man Season 1 OVA (optional)",
            "One Punch Man Season 2 (JC Staff)",
            "One Punch Man Season 2 OVA (optional)",
            "Tip: The webcomic/manga far surpasses the anime past S1",
        ],
    },
    "black clover": {
        "title": "Black Clover",
        "order": [
            "Black Clover (TV, 170 eps — use filler guide)",
            "Black Clover: Sword of the Wizard King (Movie, Netflix 2023)",
            "Black Clover Season 2: Ryuuzechi no Majo (upcoming)",
        ],
    },
    "seven deadly sins": {
        "title": "Seven Deadly Sins (Nanatsu no Taizai)",
        "order": [
            "Nanatsu no Taizai Season 1 (A-1 Pictures)",
            "Nanatsu no Taizai Season 2: Imashime no Fukkatsu",
            "Nanatsu no Taizai Season 3: Kamigami no Gekirin",
            "Nanatsu no Taizai Season 4: Fundo no Shinpan",
            "Nanatsu no Taizai: Enshuu no Purgatory (Movie, Netflix)",
            "Mokushiroku no Yonkishi (Four Knights of the Apocalypse — Sequel)",
        ],
    },
    "gundam": {
        "title": "Gundam Series",
        "order": [
            "— Universal Century (recommended first-time order) —",
            "Mobile Suit Gundam (1979 TV or Movie Trilogy) — Start here",
            "Mobile Suit Zeta Gundam (1985)",
            "Mobile Suit Gundam ZZ (1986, optional)",
            "Mobile Suit Gundam: Char's Counterattack (Movie, 1988)",
            "Mobile Suit Gundam Unicorn (OVA, 2010–2014) — Masterpiece",
            "Mobile Suit Gundam Narrative (Movie, 2018)",
            "Mobile Suit Gundam: Hathaway (Movie, 2021)",
            "— Standalone Alternate Universes (any order) —",
            "Gundam Wing — hugely popular standalone (AC Universe)",
            "Gundam SEED / SEED Destiny (CE Universe)",
            "Gundam 00 (AD Universe) — great modern entry point",
            "The Witch from Mercury (2022) — best beginner entry",
        ],
    },
    "higurashi": {
        "title": "Higurashi: When They Cry",
        "order": [
            "Higurashi no Naku Koro ni Season 1 (2006) — Question arcs",
            "Higurashi no Naku Koro ni Kai Season 2 (2007) — Answer arcs",
            "Higurashi no Naku Koro ni Rei (OVA, optional)",
            "Higurashi no Naku Koro ni Kira (OVA, optional)",
            "Higurashi no Naku Koro ni Gou (2020 Season 3) — New story",
            "Higurashi no Naku Koro ni Sotsu (2021 Season 4)",
            "Tip: Watch S1+S2 before the 2020 continuation",
        ],
    },
    "pokemon": {
        "title": "Pokémon Anime",
        "order": [
            "Pokemon Indigo League (Original Series, 1997) — the classic start",
            "Pokemon: The First Movie (optional, fits after Indigo League)",
            "— OR skip straight to modern —",
            "Pokemon Journeys: The Series (2019, standalone-friendly)",
            "Pokemon Ultimate Journeys (Ash's final championship arc)",
            "Pokemon: To Be a Pokemon Master (Ash's finale episodes)",
            "Pokemon Horizons: The Series (2023 — new protagonist, best new-viewer entry)",
            "Tip: Horizons is the best entry point for new viewers",
        ],
    },
    "digimon": {
        "title": "Digimon Series",
        "order": [
            "Digimon Adventure (1999) — the original, start here",
            "Digimon Adventure 02 (2000) — direct sequel to Adventure",
            "Digimon Tamers (2001, standalone) — darker tone, fan favourite",
            "Digimon Frontier (2002, standalone) — humans become Digimon",
            "Digimon Data Squad/Savers (2006, standalone)",
            "Digimon Adventure tri. (2015) — sequel to original Adventure",
            "Digimon Adventure: Last Evolution Kizuna (Movie, 2020)",
            "Digimon Adventure: (2020 reboot, standalone)",
            "Digimon Ghost Game (2021, standalone)",
            "Tip: Start with Adventure (1999) or Tamers for the best experience",
        ],
    },
    "no game no life": {
        "title": "No Game No Life",
        "order": [
            "No Game No Life (TV, 12 eps)",
            "No Game No Life: Zero (Movie, prequel — can watch before or after TV)",
            "Tip: Light novel continues far beyond the anime",
        ],
    },
    "log horizon": {
        "title": "Log Horizon",
        "order": [
            "Log Horizon Season 1",
            "Log Horizon Season 2: Nishikaze no Ryodan",
            "Log Horizon Season 3: Entaku Houkai",
        ],
    },
    "re:creators": {
        "title": "Re:Creators",
        "order": [
            "Re:Creators (TV, 22 eps) — watch in order",
            "Re:Creators: Summation (Recap special, optional)",
            "Tip: Single standalone series — no complex order needed",
        ],
    },
    "made in abyss": {
        "title": "Made in Abyss",
        "order": [
            "Made in Abyss Season 1",
            "Made in Abyss: Journey's Dawn (Movie 1, recap — optional)",
            "Made in Abyss: Wandering Twilight (Movie 2, recap — optional)",
            "Made in Abyss: Dawn of the Deep Soul (Movie 3, new content — canon)",
            "Made in Abyss: The Golden City of the Scorching Sun (Season 2)",
        ],
    },
    "violet evergarden": {
        "title": "Violet Evergarden",
        "order": [
            "Violet Evergarden (TV, 13 eps)",
            "Violet Evergarden: Eternity and the Auto Memory Doll (Movie, side story)",
            "Violet Evergarden: The Movie (2020, main conclusion)",
        ],
    },
}

WATCH_ORDER_ALIASES = {
    # Attack on Titan
    "aot": "attack on titan", "shingeki": "attack on titan", "snk": "attack on titan",
    # Dragon Ball
    "dbz": "dragon ball", "dbs": "dragon ball", "db": "dragon ball",
    "dragon ball z": "dragon ball", "dragon ball super": "dragon ball",
    # Naruto
    "shippuden": "naruto", "naruto shippuden": "naruto", "boruto": "naruto",
    # Bleach
    "tybw": "bleach", "thousand year blood war": "bleach",
    # Hunter x Hunter
    "hxh": "hunter x hunter",
    # Demon Slayer
    "kimetsu": "demon slayer", "kimetsu no yaiba": "demon slayer",
    # My Hero Academia
    "mha": "my hero academia", "bnha": "my hero academia",
    "boku no hero": "my hero academia", "hero academia": "my hero academia",
    # Sword Art Online
    "sao": "sword art online",
    # Re:Zero
    "rezero": "re:zero", "re zero": "re:zero",
    # Evangelion
    "nge": "evangelion", "eva": "evangelion", "neon genesis": "evangelion",
    # Code Geass
    "geass": "code geass", "lelouch": "code geass",
    # JoJo
    "jjba": "jojo", "jojos": "jojo", "jojo's bizarre adventure": "jojo",
    # Steins;Gate
    "steinsgate": "steins;gate", "steins gate": "steins;gate", "sg": "steins;gate",
    # Monogatari
    "bakemonogatari": "monogatari",
    # Toaru
    "index": "toaru", "railgun": "toaru", "accelerator": "toaru",
    "a certain magical index": "toaru",
    # Overlord
    "ainz": "overlord",
    # KonoSuba
    "kono suba": "konosuba", "kazuma": "konosuba",
    # Tensura / Slime
    "slime": "tensura", "rimuru": "tensura",
    "that time i got reincarnated as a slime": "tensura",
    # DanMachi
    "is it wrong": "danmachi", "bell cranel": "danmachi", "dungeon": "danmachi",
    # Jujutsu Kaisen
    "jjk": "jujutsu kaisen", "jujutsu": "jujutsu kaisen",
    # Chainsaw Man
    "csm": "chainsaw man", "denji": "chainsaw man",
    # Tokyo Ghoul
    "tg": "tokyo ghoul", "kaneki": "tokyo ghoul",
    # Fullmetal Alchemist
    "fma": "fullmetal alchemist", "fmab": "fullmetal alchemist",
    "brotherhood": "fullmetal alchemist",
    # Fairy Tail
    "ft": "fairy tail", "natsu": "fairy tail",
    # One Punch Man
    "opm": "one punch man", "saitama": "one punch man",
    # Fate
    "fate stay night": "fate", "fate zero": "fate", "fgo": "fate",
    # Black Clover
    "bc": "black clover", "asta": "black clover",
    # Seven Deadly Sins
    "sds": "seven deadly sins", "nanatsu": "seven deadly sins",
    "nanatsu no taizai": "seven deadly sins",
    # Gundam
    "mobile suit gundam": "gundam", "witch from mercury": "gundam",
    "gundam wing": "gundam", "gundam seed": "gundam", "gundam 00": "gundam",
    "iron-blooded orphans": "gundam", "ibo": "gundam",
    # Higurashi
    "when they cry": "higurashi", "higurashi when they cry": "higurashi",
    "watanagashi": "higurashi",
    # Pokemon
    "pokémon": "pokemon", "ash": "pokemon", "pikachu": "pokemon",
    "pocket monsters": "pokemon",
    # Digimon
    "digimon adventure": "digimon", "agumon": "digimon",
    # No Game No Life
    "ngnl": "no game no life", "no game": "no game no life",
    # Log Horizon
    "lh": "log horizon",
    # Made in Abyss
    "mia": "made in abyss", "abyss": "made in abyss",
    # Violet Evergarden
    "ve": "violet evergarden", "violet": "violet evergarden",
    # Re:Creators
    "recreators": "re:creators",
}

QUIZ_QUESTIONS = [
    {"question": "Which studio produced Fullmetal Alchemist: Brotherhood?", "options": ["Bones", "Madhouse", "MAPPA", "Sunrise"], "answer": "Bones"},
    {"question": "In Death Note, which shinigami drops his notebook in the human world?", "options": ["Ryuk", "Rem", "Gelus", "Sidoh"], "answer": "Ryuk"},
    {"question": "Which anime features a notebook that kills anyone whose name is written in it?", "options": ["Death Note", "Mirai Nikki", "Elfen Lied", "Another"], "answer": "Death Note"},
    {"question": "Which studio produced Demon Slayer: Kimetsu no Yaiba?", "options": ["ufotable", "MAPPA", "Wit Studio", "A-1 Pictures"], "answer": "ufotable"},
    {"question": "What is Gon Freecss searching for in Hunter x Hunter?", "options": ["His father", "A legendary monster", "The Hunter exam", "The King"], "answer": "His father"},
    {"question": "In My Hero Academia, what is Izuku Midoriya's hero name?", "options": ["Deku", "Shoto", "Kacchan", "Froppy"], "answer": "Deku"},
    {"question": "Which anime features the Phantom Troupe criminal organisation?", "options": ["Hunter x Hunter", "Bleach", "Fairy Tail", "Naruto"], "answer": "Hunter x Hunter"},
    {"question": "Who is the author of One Piece?", "options": ["Eiichiro Oda", "Akira Toriyama", "Masashi Kishimoto", "Tite Kubo"], "answer": "Eiichiro Oda"},
    {"question": "What is the name of the pirate crew led by Monkey D. Luffy?", "options": ["Straw Hat Pirates", "Whitebeard Pirates", "Red Hair Pirates", "Big Mom Pirates"], "answer": "Straw Hat Pirates"},
    {"question": "In Dragon Ball Z, who is Gohan's father?", "options": ["Goku", "Vegeta", "Piccolo", "Krillin"], "answer": "Goku"},
    {"question": "In Sword Art Online, what is the name of the first virtual game?", "options": ["Sword Art Online", "ALfheim Online", "Gun Gale Online", "Ordinal Scale"], "answer": "Sword Art Online"},
    {"question": "Which anime features 'Stands' as supernatural abilities?", "options": ["JoJo's Bizarre Adventure", "Bleach", "Hunter x Hunter", "Naruto"], "answer": "JoJo's Bizarre Adventure"},
    {"question": "What is the name of the main protagonist in Steins;Gate?", "options": ["Rintaro Okabe", "Kurisu Makise", "Mayuri Shiina", "Itaru Hashida"], "answer": "Rintaro Okabe"},
    {"question": "In Neon Genesis Evangelion, what does NERV fight against?", "options": ["Angels", "Titans", "Hollows", "Demons"], "answer": "Angels"},
    {"question": "Which anime is set in Ouran Academy?", "options": ["Ouran High School Host Club", "Toradora", "Clannad", "K-On!"], "answer": "Ouran High School Host Club"},
]

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🔍 Search"), KeyboardButton("🏆 Top Anime")],
        [KeyboardButton("📺 Season"), KeyboardButton("🎲 Random")],
        [KeyboardButton("🎭 Character"), KeyboardButton("🏢 Studio")],
        [KeyboardButton("📚 Genre"), KeyboardButton("🔥 Trending")],
        [KeyboardButton("📰 News"), KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
)

HELP_TEXT = (
    "🤖 Ani Zeo v3.0  |  Ultimate Anime Companion\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🎌 ANIME GUIDE\n"
    "  /beginner             Guide for newcomers\n"
    "  /starterpack          10 essential anime\n"
    "  /recommend <anime>    Shows similar to one you love\n"
    "  /recommend <genre>    Top picks in a genre\n\n"
    "🔎 ANIME SEARCH & INFO\n"
    "  /search <anime>       Full details + poster + relations\n"
    "  /similar <anime>      Similar anime picks\n"
    "  /compare <a> vs <b>   Compare two anime\n"
    "  /trailer <anime>      Official trailer link\n"
    "  /dub <anime>          Dub language availability\n\n"
    "📚 MANGA SYSTEM\n"
    "  /manga <title>        Manga details + cover\n"
    "  /topmanga             Top 10 manga of all time\n"
    "  /randommanga          Random manga pick\n"
    "  /mangagenre <genre>   Top manga by genre\n\n"
    "👤 PROFILE & TRACKING\n"
    "  /profile              Your anime profile & stats\n"
    "  /stats                Same as /profile\n"
    "  /watchlist            Your watchlist (all)\n"
    "  /watchlist add <anime> [status]\n"
    "  /watchlist remove <anime>\n"
    "  /watchlist watching|completed|planned|dropped\n\n"
    "👥 CHARACTERS & STUDIOS\n"
    "  /character <anime>    Characters + voice actors\n"
    "  /studio <anime>       Studio info\n\n"
    "📊 RANKINGS\n"
    "  /top                  Top 10 anime\n"
    "  /trending             Trending right now\n"
    "  /genre <genre>        10 picks, refreshed each time\n\n"
    "📅 SEASONAL\n"
    "  /season               Top airing this season\n"
    "  /upcoming             Upcoming anime\n"
    "  /airing               Airing today\n"
    "  /schedule <day>       Day schedule\n\n"
    "🎲 DISCOVERY\n"
    "  /random               Random anime pick\n"
    "  /order <series>       Watch order (35+ franchises)\n"
    "  /quiz                 Anime trivia quiz\n\n"
    "⭐ FAVOURITES\n"
    "  /favorite add <anime>\n"
    "  /favorite remove <anime>\n"
    "  /favorites            Your saved anime\n\n"
    "📰 NEWS\n"
    "  /news                 Latest anime news\n\n"
    "❓ /help — Show this menu\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Powered by AniList & Jikan API  |  v3.0"
)

# ── Helpers ────────────────────────────────────────────────────────────────

def anilist(query_str, variables=None):
    r = requests.post(
        ANILIST_URL,
        json={"query": query_str, "variables": variables or {}},
        timeout=15,
    )
    return r.json()

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def load_favorites():
    if FAVORITES_FILE.exists():
        try:
            return json.loads(FAVORITES_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_favorites(data):
    FAVORITES_FILE.write_text(json.dumps(data, indent=2))

def fmt_score(score):
    if not score:
        return "N/A"
    return f"{score / 10:.1f}/10"

def fmt_season(season, year):
    if season and year:
        return f"{season.capitalize()} {year}"
    return str(year) if year else None

def get_rank(rankings):
    entry = next((r for r in (rankings or []) if r.get("allTime") and r.get("type") == "RATED"), None)
    return f"#{entry['rank']}" if entry else None

def get_platforms(external_links):
    platforms = []
    for link in (external_links or []):
        site = link.get("site", "")
        if site in STREAMING_SITES:
            platforms.append(site)
    return list(dict.fromkeys(platforms))  # deduplicate, preserve order

# ── Reply Keyboard Handler ─────────────────────────────────────────────────

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text == "🔍 Search":
        await update.message.reply_text("Use /search followed by an anime name.\nExample: /search naruto")
    elif text == "🏆 Top Anime":
        await top(update, context)
    elif text == "📺 Season":
        await season(update, context)
    elif text == "🎲 Random":
        await random_anime(update, context)
    elif text == "🎭 Character":
        await update.message.reply_text("Use /character followed by an anime name.\nExample: /character death note")
    elif text == "🏢 Studio":
        await update.message.reply_text("Use /studio followed by an anime name.\nExample: /studio naruto")
    elif text == "📚 Genre":
        await update.message.reply_text(
            "Use /genre followed by a genre name.\nExample: /genre action\n\n"
            "Available: action, adventure, comedy, drama, fantasy, horror, mystery, "
            "romance, sci-fi, slice of life, sports, supernatural, thriller, mecha, "
            "music, psychological, historical, isekai, shounen, shoujo"
        )
    elif text == "🔥 Trending":
        await trending(update, context)
    elif text == "📰 News":
        await news(update, context)
    elif text == "❓ Help":
        await help_command(update, context)

# ── Commands ───────────────────────────────────────────────────────────────

START_INLINE = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🔍 Search", callback_data="cmd:search"),
        InlineKeyboardButton("🔥 Trending", callback_data="cmd:trending"),
    ],
    [
        InlineKeyboardButton("📅 Season", callback_data="cmd:season"),
        InlineKeyboardButton("📺 Airing", callback_data="cmd:airing"),
    ],
    [
        InlineKeyboardButton("📰 News", callback_data="cmd:news"),
        InlineKeyboardButton("🎲 Random", callback_data="cmd:random"),
    ],
    [
        InlineKeyboardButton("❓ Help", callback_data="cmd:help"),
    ],
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🎌 *Ani Zeo*\n"
        "_Your Anime Companion_\n\n"
        "Welcome! Explore anime info, rankings, trailers,\n"
        "seasonal picks, and much more.\n\n"
        "📊 *Version:* 2.0\n"
        "⚙️ *Commands:* 20\n\n"
        "Tap a button below or type any /command directly.\n\n"
        "_Powered by AniList & Jikan API_\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "*Ani Zeo v2.0*"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=START_INLINE)
    await update.message.reply_text("Quick-access menu:", reply_markup=MAIN_KEYBOARD)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_KEYBOARD)

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide an anime name.\nExample: /search naruto")
        return

    query = " ".join(context.args)
    try:
        try:
            update_profile(update.effective_user.id, update.effective_user.username, command="search", anime_search=True)
        except Exception:
            pass

        result = anilist("""
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    title { romaji english native }
    coverImage { large }
    averageScore popularity
    rankings { rank type allTime }
    episodes status season seasonYear
    genres
    studios(isMain: true) { nodes { name } }
    source duration
    description(asHtml: false)
    trailer { id site }
    externalLinks { url site type }
    relations {
      edges {
        relationType(version: 2)
        node { title { romaji english } type }
      }
    }
  }
}
        """, {"search": query})

        media = result.get("data", {}).get("Media")
        if not media:
            await update.message.reply_text("Anime not found.")
            return

        title_romaji = media["title"].get("romaji", "N/A")
        title_english = media["title"].get("english")
        title_native = media["title"].get("native")
        cover = media.get("coverImage", {}).get("large")
        score = fmt_score(media.get("averageScore"))
        rank = get_rank(media.get("rankings", []))
        popularity = media.get("popularity")
        episodes = media.get("episodes") or "N/A"
        status = STATUS_MAP.get(media.get("status", ""), media.get("status", "N/A"))
        season_str = fmt_season(media.get("season"), media.get("seasonYear"))
        genres = ", ".join(media.get("genres", [])[:5]) or None
        studios = ", ".join(n["name"] for n in media.get("studios", {}).get("nodes", [])) or None
        source = SOURCE_MAP.get(media.get("source", ""), media.get("source"))
        duration = f"{media['duration']} min/ep" if media.get("duration") else None
        synopsis = strip_html(media.get("description") or "")
        if len(synopsis) > 900:
            synopsis = synopsis[:900] + "..."

        trailer = media.get("trailer")
        trailer_url = None
        if trailer and trailer.get("site") == "youtube":
            trailer_url = f"https://www.youtube.com/watch?v={trailer['id']}"

        platforms = get_platforms(media.get("externalLinks", []))

        # Relations: prequel / sequel
        rel_edges = media.get("relations", {}).get("edges", [])
        related_parts = []
        for edge in rel_edges:
            rt = edge.get("relationType", "")
            node = edge.get("node", {})
            if rt in ("PREQUEL", "SEQUEL") and node.get("type") == "ANIME":
                t = node["title"].get("english") or node["title"].get("romaji", "")
                if t:
                    related_parts.append(f"{'⬅ Prequel' if rt == 'PREQUEL' else '➡ Sequel'}: {t}")

        lines = [f"🎌 {title_romaji}"]
        if title_english and title_english != title_romaji:
            lines.append(f"🇬🇧 {title_english}")
        if title_native:
            lines.append(f"🇯🇵 {title_native}")
        lines.append("")
        lines.append(f"⭐ Score: {score}")
        if rank:
            lines.append(f"🏆 Rank: {rank}")
        if popularity:
            lines.append(f"📈 Popularity: #{popularity:,}")
        lines.append(f"📺 Episodes: {episodes}")
        lines.append(f"📌 Status: {status}")
        if season_str:
            lines.append(f"📅 Season: {season_str}")
        if genres:
            lines.append(f"🎭 Genres: {genres}")
        if studios:
            lines.append(f"🏢 Studio: {studios}")
        if source:
            lines.append(f"📖 Source: {source}")
        if duration:
            lines.append(f"⏱ Duration: {duration}")
        if trailer_url:
            lines.append(f"🎬 Trailer: {trailer_url}")
        if platforms:
            lines.append(f"📡 Watch on: {', '.join(platforms)}")
        if related_parts:
            lines.append(f"🔗 {' | '.join(related_parts[:3])}")
        if synopsis:
            lines.append(f"\n📝 Synopsis:\n{synopsis}")

        caption = "\n".join(lines)

        if cover:
            try:
                await update.message.reply_photo(photo=cover, caption=caption[:1024])
                if len(caption) > 1024:
                    await update.message.reply_text(caption[1024:])
                return
            except Exception:
                pass

        await update.message.reply_text(caption)

    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = requests.get("https://api.jikan.moe/v4/top/anime", params={"limit": 10}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Could not fetch top anime. Please try again.")
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = ["🏆 Top 10 Anime of All Time\n"]
        for i, anime in enumerate(results, start=1):
            title = anime.get("title", "N/A")
            score = anime.get("score") or "N/A"
            lines.append(f"{medals.get(i, f'{i}.')} {title}\n    ⭐ Score: {score}")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = anilist("""
query {
  Page(page: 1, perPage: 10) {
    media(type: ANIME, sort: [TRENDING_DESC], isAdult: false) {
      title { romaji }
      averageScore episodes status
    }
  }
}
        """)
        items = result.get("data", {}).get("Page", {}).get("media", [])
        if not items:
            await update.message.reply_text("Could not fetch trending anime. Please try again.")
            return

        lines = ["🔥 Trending Anime Right Now\n"]
        for i, anime in enumerate(items, start=1):
            title = anime["title"].get("romaji", "N/A")
            score = fmt_score(anime.get("averageScore"))
            episodes = anime.get("episodes") or "Ongoing"
            lines.append(f"{i}. {title}\n   ⭐ {score} | 📺 {episodes} eps")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = anilist("""
query {
  Page(page: 1, perPage: 8) {
    media(type: ANIME, status: RELEASING, sort: [UPDATED_AT_DESC], isAdult: false) {
      title { romaji }
      averageScore
      nextAiringEpisode { episode timeUntilAiring }
      siteUrl
    }
  }
}
        """)
        items = result.get("data", {}).get("Page", {}).get("media", [])
        if not items:
            await update.message.reply_text("No recent updates available.")
            return

        today = datetime.now().strftime("%d %b %Y")
        lines = [f"📰 Anime Updates — {today}\n"]
        for anime in items:
            title = anime["title"].get("romaji", "N/A")
            score = fmt_score(anime.get("averageScore"))
            nae = anime.get("nextAiringEpisode")
            if nae:
                ep = nae.get("episode", "?")
                hours = nae.get("timeUntilAiring", 0) // 3600
                lines.append(f"📺 {title}\n   ⭐ {score} | Ep {ep} in ~{hours}h")
            else:
                lines.append(f"📺 {title}\n   ⭐ {score}")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def trailer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide an anime name.\nExample: /trailer attack on titan")
        return

    query = " ".join(context.args)
    try:
        result = anilist("""
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    title { romaji }
    trailer { id site }
  }
}
        """, {"search": query})

        media = result.get("data", {}).get("Media")
        if not media:
            await update.message.reply_text("Anime not found.")
            return

        title = media["title"].get("romaji", "N/A")
        tr = media.get("trailer")
        if tr and tr.get("site") == "youtube":
            url = f"https://www.youtube.com/watch?v={tr['id']}"
            await update.message.reply_text(f"🎬 {title}\n\n{url}")
        else:
            await update.message.reply_text(f"🎬 {title}\n\nTrailer unavailable.")
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def random_anime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        anime = None
        for _ in range(10):
            r = requests.get("https://api.jikan.moe/v4/random/anime", timeout=10)
            candidate = r.json().get("data")
            if not candidate:
                continue
            genres = {g.get("name", "").lower() for g in candidate.get("genres", [])}
            explicit = {g.get("name", "").lower() for g in candidate.get("explicit_genres", [])}
            if (genres | explicit) & EXCLUDED_GENRES:
                continue
            anime = candidate
            break

        if not anime:
            await update.message.reply_text("Could not fetch a random anime. Please try again.")
            return

        title = anime.get("title", "N/A")
        episodes = anime.get("episodes") or "N/A"
        score = anime.get("score") or "N/A"
        status = anime.get("status", "N/A")
        synopsis = anime.get("synopsis") or "No synopsis available."
        if len(synopsis) > 1000:
            synopsis = synopsis[:1000] + "..."

        await update.message.reply_text(
            f"🎲 Random Anime\n\n"
            f"📺 Title: {title}\n"
            f"🎬 Episodes: {episodes}\n"
            f"⭐ Score: {score}\n"
            f"📌 Status: {status}\n\n"
            f"📖 Synopsis:\n{synopsis}"
        )
    except Exception:
        await update.message.reply_text("Could not fetch a random anime. Please try again.")

async def similar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide an anime name.\nExample: /similar death note")
        return

    query = " ".join(context.args)
    try:
        r = requests.get("https://api.jikan.moe/v4/anime", params={"q": query, "limit": 1}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Anime not found.")
            return

        anime = results[0]
        anime_id = anime["mal_id"]
        anime_title = anime.get("title", "N/A")

        r2 = requests.get(f"https://api.jikan.moe/v4/anime/{anime_id}/recommendations", timeout=10)
        recs = r2.json().get("data", [])[:5]

        if not recs:
            await update.message.reply_text(f"No similar anime found for {anime_title}.")
            return

        lines = [f"🔍 Anime similar to {anime_title}\n"]
        for i, rec in enumerate(recs, start=1):
            entry = rec.get("entry", {})
            title = entry.get("title", "N/A")
            rec_id = entry.get("mal_id")
            episodes = "N/A"
            score_display = "Score unavailable"
            if rec_id:
                try:
                    d = requests.get(f"https://api.jikan.moe/v4/anime/{rec_id}", timeout=10)
                    detail = d.json().get("data", {})
                    episodes = detail.get("episodes") or "N/A"
                    sc = detail.get("score")
                    score_display = str(sc) if sc else "Score unavailable"
                except Exception:
                    pass
            lines.append(f"🎌 {i}. {title}\n   ⭐ {score_display} | 📺 {episodes} eps")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /compare <anime1> vs <anime2>\nExample: /compare death note vs naruto")
        return

    query = " ".join(context.args)
    parts = re.split(r'\s+vs\s+', query, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        await update.message.reply_text("Please separate the two anime with 'vs'.\nExample: /compare death note vs naruto")
        return

    a1_query, a2_query = parts[0].strip(), parts[1].strip()

    async def fetch_anime(q):
        r = requests.get("https://api.jikan.moe/v4/anime", params={"q": q, "limit": 1}, timeout=10)
        data = r.json().get("data", [])
        return data[0] if data else None

    try:
        a1 = await fetch_anime(a1_query)
        a2 = await fetch_anime(a2_query)

        if not a1 or not a2:
            missing = a1_query if not a1 else a2_query
            await update.message.reply_text(f"Could not find: {missing}")
            return

        def val(anime, key, fallback="N/A"):
            v = anime.get(key)
            return str(v) if v else fallback

        genres1 = ", ".join(g["name"] for g in a1.get("genres", [])[:3]) or "N/A"
        genres2 = ", ".join(g["name"] for g in a2.get("genres", [])[:3]) or "N/A"
        studio1 = a1.get("studios", [{}])[0].get("name", "N/A") if a1.get("studios") else "N/A"
        studio2 = a2.get("studios", [{}])[0].get("name", "N/A") if a2.get("studios") else "N/A"

        t1 = a1.get("title", "Anime 1")
        t2 = a2.get("title", "Anime 2")

        msg = (
            f"⚔️ Anime Comparison\n\n"
            f"📌 {t1}  vs  {t2}\n"
            f"{'─' * 30}\n"
            f"⭐ Score:      {val(a1, 'score')}  |  {val(a2, 'score')}\n"
            f"📺 Episodes:   {val(a1, 'episodes')}  |  {val(a2, 'episodes')}\n"
            f"📌 Status:     {val(a1, 'status')}  |  {val(a2, 'status')}\n"
            f"👥 Members:    {a1.get('members', 'N/A'):,}  |  {a2.get('members', 'N/A'):,}\n"
            f"🏢 Studio:     {studio1}  |  {studio2}\n"
            f"🎭 Genres:     {genres1}  |  {genres2}"
        )
        await update.message.reply_text(msg)
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide an anime name.\nExample: /character naruto")
        return

    query = " ".join(context.args)
    try:
        result = anilist("""
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    title { romaji }
    characters(sort: [ROLE, RELEVANCE], page: 1, perPage: 8) {
      edges {
        role
        voiceActors(sort: RELEVANCE) {
          name { full }
          language
        }
        node {
          name { full native }
          gender
          image { medium }
        }
      }
    }
  }
}
        """, {"search": query})

        media = result.get("data", {}).get("Media")
        if not media:
            await update.message.reply_text("Anime not found.")
            return

        title = media["title"].get("romaji", "N/A")
        edges = media.get("characters", {}).get("edges", [])
        main_chars = [e for e in edges if e.get("role") == "MAIN"][:5]
        if not main_chars:
            main_chars = edges[:5]

        if not main_chars:
            await update.message.reply_text(f"No characters found for {title}.")
            return

        lines = [f"👥 Characters — {title}\n"]
        for i, edge in enumerate(main_chars, start=1):
            node = edge.get("node", {})
            name = node.get("name", {}).get("full", "N/A")
            native = node.get("name", {}).get("native", "")
            role = edge.get("role", "N/A").capitalize()
            gender = node.get("gender") or ""

            entry = f"{i}. {name}"
            if native:
                entry += f" ({native})"
            entry += f"\n   🎭 {role}"
            if gender:
                entry += f"  |  {gender}"

            # Voice actors
            vas = edge.get("voiceActors", [])
            ja_va = next((v for v in vas if v.get("language", "").upper() == "JAPANESE"), None)
            en_va = next((v for v in vas if v.get("language", "").upper() == "ENGLISH"), None)
            if ja_va:
                entry += f"\n   🇯🇵 {ja_va['name']['full']}"
            if en_va:
                entry += f"\n   🇬🇧 {en_va['name']['full']}"

            lines.append(entry)

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def studio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide an anime name.\nExample: /studio naruto")
        return

    query = " ".join(context.args)
    try:
        result = anilist("""
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    title { romaji }
    studios {
      edges {
        isMain
        node { id name isAnimationStudio favourites siteUrl }
      }
    }
  }
}
        """, {"search": query})

        media = result.get("data", {}).get("Media")
        if not media:
            await update.message.reply_text("Anime not found.")
            return

        title = media["title"].get("romaji", "N/A")
        edges = media.get("studios", {}).get("edges", [])
        main_studios = [e for e in edges if e.get("isMain")]
        if not main_studios:
            main_studios = edges

        if not main_studios:
            await update.message.reply_text(f"No studio information found for {title}.")
            return

        lines = [f"🏢 Studio Info — {title}\n"]
        for edge in main_studios:
            node = edge.get("node", {})
            name = node.get("name", "N/A")
            is_animation = node.get("isAnimationStudio", False)
            studio_type = "Animation Studio" if is_animation else "Producer"
            favourites = node.get("favourites", 0)
            site = node.get("siteUrl", "")

            entry = f"🎬 {name}\n   📁 Type: {studio_type}"
            if favourites:
                entry += f"\n   ❤️ Favourites: {favourites:,}"
            if site:
                entry += f"\n   🔗 {site}"
            lines.append(entry)

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

def _franchise_key(title: str) -> str:
    """Return a short normalised key used to detect duplicate franchise entries.

    Strategy:
    - Collapse all known sequel/arc separators so "Gintama. Shirogane…",
      "Gintama Movie 2: …", "Gintama'", "Gintama°" all reduce to "gintama".
    - Use a two-word prefix so "Dragon Ball Z" and "Dragon Ball Super" share
      the same key "dragon ball".
    """
    t = title.lower()
    # "Word. Word" is an anime subtitle separator (Gintama. Shirogane…) → treat as colon
    t = re.sub(r"(\w)\.\s+", r"\1: ", t)
    # Strip ": subtitle" and everything after any colon
    t = re.sub(r"\s*:.*", "", t)
    # Strip remaining trailing sequel punctuation  (', °, !, ., …)
    t = re.sub(r"[.''°!?\u2026]+$", "", t)
    # Strip parenthetical year — (2019)
    t = re.sub(r"\s*\(\d{4}\)", "", t)
    # Strip season markers: "2nd Season", "Season 2"
    t = re.sub(r"\s+\d+(st|nd|rd|th)\s+season\b.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+season\s+\d+\b.*", "", t, flags=re.IGNORECASE)
    # Strip Movie / OVA / ONA / Special suffix (catches "Gintama Movie 2 …")
    t = re.sub(r"\s+(?:movie|film|ova|ona|special)\b.*", "", t, flags=re.IGNORECASE)
    # Strip trailing roman numerals and bare numbers
    t = re.sub(r"\s+[ivx]+$", "", t)
    t = re.sub(r"\s+\d+$", "", t)
    t = " ".join(t.split())
    words = t.split()
    return " ".join(words[:2]) if len(words) >= 2 else t


async def genre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Please provide a genre.\nExample: /genre action")
        return

    query = " ".join(context.args).lower().strip()
    genre_id = GENRE_MAP.get(query)

    if not genre_id:
        supported = ", ".join(sorted(set(k for k in GENRE_MAP if k not in ("scifi", "science fiction"))))
        await update.message.reply_text(f"Genre '{query}' not recognised.\n\nSupported genres:\n{supported}")
        return

    try:
        # Fetch a random page from the top 100 so results feel fresh each time
        page = random.randint(1, 4)
        r = requests.get(
            "https://api.jikan.moe/v4/anime",
            params={"genres": genre_id, "order_by": "score", "sort": "desc", "limit": 25, "page": page},
            timeout=10,
        )
        results = r.json().get("data", [])
        if not results:
            # Fallback to page 1
            r = requests.get(
                "https://api.jikan.moe/v4/anime",
                params={"genres": genre_id, "order_by": "score", "sort": "desc", "limit": 25},
                timeout=10,
            )
            results = r.json().get("data", [])
        if not results:
            await update.message.reply_text(f"No anime found for genre '{query.title()}'.")
            return

        random.shuffle(results)  # shuffle within the page for variety

        seen_keys: set[str] = set()
        diverse: list = []
        for anime in results:
            key = _franchise_key(anime.get("title", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                diverse.append(anime)
            if len(diverse) == 10:
                break

        try:
            update_profile(update.effective_user.id, update.effective_user.username, command="genre", genre=query)
        except Exception:
            pass

        lines = [f"🎭 {query.title()} — 10 Picks\n"]
        for i, anime in enumerate(diverse, start=1):
            title = anime.get("title", "N/A")
            score = anime.get("score") or "N/A"
            episodes = anime.get("episodes") or "N/A"
            lines.append(f"{i}. {title}\n   ⭐ {score} | 📺 {episodes} eps")

        lines.append("\nRun /genre again for a different set!")
        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def season(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = requests.get("https://api.jikan.moe/v4/seasons/now", params={"limit": 25}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Could not fetch seasonal anime. Please try again.")
            return

        today = datetime.now().strftime("%d %b %Y")
        top10 = sorted(results, key=lambda a: a.get("score") or 0, reverse=True)[:10]

        lines = [f"📅 Top Airing Anime This Season\n{today}\n"]
        for i, anime in enumerate(top10, start=1):
            title = anime.get("title", "N/A")
            score = anime.get("score") or "N/A"
            episodes = anime.get("episodes") or "Ongoing"
            lines.append(f"{i}. {title}\n⭐ {score} | 📺 {episodes} eps")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def airing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        today_name = datetime.now().strftime("%A").lower()
        r = requests.get("https://api.jikan.moe/v4/schedules", params={"filter": today_name, "limit": 10}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("No anime found airing today.")
            return

        label = datetime.now().strftime("%A, %d %b %Y")
        lines = [f"📡 Airing Today — {label}\n"]
        for i, anime in enumerate(results, start=1):
            title = anime.get("title", "N/A")
            score = anime.get("score") or "N/A"
            episodes = anime.get("episodes") or "Ongoing"
            lines.append(f"{i}. {title}\n⭐ {score} | 📺 {episodes} eps")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if not context.args:
        await update.message.reply_text("Please provide a day.\nExample: /schedule monday")
        return

    day = context.args[0].lower()
    if day not in valid_days:
        await update.message.reply_text(f"Invalid day. Choose from:\n{', '.join(valid_days)}")
        return

    try:
        r = requests.get("https://api.jikan.moe/v4/schedules", params={"filter": day, "limit": 10}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text(f"No anime found airing on {day.capitalize()}.")
            return

        lines = [f"📅 Airing on {day.capitalize()}\n"]
        for i, anime in enumerate(results, start=1):
            title = anime.get("title", "N/A")
            score = anime.get("score") or "N/A"
            episodes = anime.get("episodes") or "Ongoing"
            lines.append(f"{i}. {title}\n⭐ {score} | 📺 {episodes} eps")

        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")

async def order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        franchise_names = sorted(WATCH_ORDERS.keys())
        franchise_list = ", ".join(franchise_names)
        await update.message.reply_text(
            f"Usage: /order <series>\nExamples: /order fate  |  /order jjk  |  /order mha\n\n"
            f"📚 {len(WATCH_ORDERS)} franchises supported:\n{franchise_list}\n\n"
            "Shortcuts: jjk, mha, fmab, opm, dbz, hxh, sao, eva, tybw, csm, slime, aot…"
        )
        return

    query = " ".join(context.args).lower().strip()
    key = WATCH_ORDER_ALIASES.get(query, query)
    data = WATCH_ORDERS.get(key)

    if not data:
        all_keys = list(WATCH_ORDERS.keys()) + list(WATCH_ORDER_ALIASES.keys())
        words = query.split()
        suggestions = sorted(set(k for k in all_keys if any(w in k for w in words) and k != query))[:4]
        msg = f"'{query}' is not in the watch order database.\n\nFor most series, just watch from Episode 1 in release order.\n"
        if suggestions:
            msg += f"\nDid you mean: {', '.join(suggestions)}?"
        msg += f"\n\nType /order to see all {len(WATCH_ORDERS)} supported franchises."
        await update.message.reply_text(msg)
        return

    lines = [f"📺 {data['title']} — Watch Order\n"]
    step = 1
    for entry in data["order"]:
        if entry:
            lines.append(f"{step}. {entry}")
            step += 1
        else:
            lines.append("")

    await update.message.reply_text("\n".join(lines))

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = random.choice(QUIZ_QUESTIONS)
    context.user_data["quiz_answer"] = q["answer"]
    opts = q["options"][:]
    random.shuffle(opts)
    buttons = [[InlineKeyboardButton(opt, callback_data=f"quiz:{opt}")] for opt in opts]
    await update.message.reply_text(
        f"🎮 Anime Quiz!\n\n{q['question']}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chosen = query.data.replace("quiz:", "", 1)
    correct = context.user_data.get("quiz_answer", "")
    if chosen == correct:
        await query.edit_message_text(f"✅ Correct!\n\nThe answer is: {correct}\n\nType /quiz to play again!")
    else:
        await query.edit_message_text(f"❌ Wrong!\n\nCorrect answer: {correct}\nYour answer: {chosen}\n\nType /quiz to try again!")

async def cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cmd = query.data.replace("cmd:", "", 1)

    dispatch = {
        "trending": trending,
        "season": season,
        "airing": airing,
        "news": news,
        "random": random_anime,
        "help": help_command,
    }

    if cmd == "search":
        await query.message.reply_text(
            "🔍 Use /search followed by an anime name.\n\nExamples:\n"
            "/search naruto\n"
            "/search attack on titan\n"
            "/search fullmetal alchemist"
        )
    elif cmd in dispatch:
        await dispatch[cmd](query, context)

async def favorite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/favorite add <anime name>\n"
            "/favorite remove <anime name>"
        )
        return

    action = context.args[0].lower()
    anime_name = " ".join(context.args[1:])
    user_id = str(update.effective_user.id)

    if action not in ("add", "remove"):
        await update.message.reply_text("Use 'add' or 'remove'.\nExample: /favorite add naruto")
        return

    favs = load_favorites()
    user_favs = favs.get(user_id, [])

    if action == "add":
        if anime_name.lower() in [f.lower() for f in user_favs]:
            await update.message.reply_text(f"'{anime_name}' is already in your favourites.")
        elif len(user_favs) >= 20:
            await update.message.reply_text("You can save up to 20 favourites. Remove some first.")
        else:
            user_favs.append(anime_name)
            favs[user_id] = user_favs
            save_favorites(favs)
            await update.message.reply_text(f"⭐ Added '{anime_name}' to your favourites!")
    else:
        match = next((f for f in user_favs if f.lower() == anime_name.lower()), None)
        if match:
            user_favs.remove(match)
            favs[user_id] = user_favs
            save_favorites(favs)
            await update.message.reply_text(f"🗑 Removed '{match}' from your favourites.")
        else:
            await update.message.reply_text(f"'{anime_name}' is not in your favourites.")

async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    favs = load_favorites()
    user_favs = favs.get(user_id, [])

    if not user_favs:
        await update.message.reply_text(
            "You have no saved favourites yet.\n\nUse /favorite add <anime> to save one!"
        )
        return

    lines = [f"⭐ Your Favourites ({len(user_favs)})\n"]
    for i, name in enumerate(user_favs, start=1):
        lines.append(f"{i}. {name}")

    await update.message.reply_text("\n".join(lines))


BEGINNER_TEXT = (
    "🌟 Welcome to Anime!\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "New to anime? Here's where to start:\n\n"
    "🏆 MUST-WATCH FIRST\n"
    "• Fullmetal Alchemist: Brotherhood\n"
    "  Perfect anime — action, story, heart\n"
    "• Death Note\n"
    "  Psychological thriller — impossible to put down\n"
    "• Demon Slayer\n"
    "  Best entry point — stunning animation, great story\n\n"
    "⚔️ ACTION & ADVENTURE\n"
    "• Attack on Titan — Epic mystery and relentless action\n"
    "• My Hero Academia — Superheroes done right\n"
    "• One Punch Man — Hilarious action comedy\n"
    "• Hunter x Hunter — Long but every arc is better than the last\n\n"
    "😂 COMEDY\n"
    "• KonoSuba — Fantasy comedy gold\n"
    "• Gintama — The funniest anime ever made\n"
    "• The Disastrous Life of Saiki K. — Absurdist genius\n\n"
    "💕 ROMANCE\n"
    "• Your Lie in April — Beautiful and emotional\n"
    "• Toradora — The classic rom-com\n"
    "• Clannad — Will make you cry (in the best way)\n\n"
    "🧠 PSYCHOLOGICAL\n"
    "• Steins;Gate — Mind-bending sci-fi masterpiece\n"
    "• Monster — Dark, complex, unforgettable\n"
    "• Code Geass — Strategy, politics, great twists\n\n"
    "🎬 FILMS\n"
    "• Spirited Away — Studio Ghibli's masterpiece\n"
    "• Your Name — The most popular anime film ever\n"
    "• Akira — The legendary classic that defined the genre\n\n"
    "💡 Beginner tips:\n"
    "• Start with 12-episode series before tackling long ones\n"
    "• Subtitles > Dubs for most shows\n"
    "• Use /search <title> to learn more about any show\n"
    "• Use /recommend <genre> for personalised picks\n"
    "• Use /order <series> for multi-season watch orders\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Type /starterpack for the 10 essential anime"
)

STARTERPACK_TEXT = (
    "🎒 The Anime Starter Pack\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "10 essential anime every fan should watch:\n\n"
    "1. Fullmetal Alchemist: Brotherhood\n"
    "   The gold standard. Perfect in every way.\n\n"
    "2. Death Note\n"
    "   The ultimate 'just one more episode' show.\n\n"
    "3. Attack on Titan\n"
    "   Gripping story with some of anime's best twists.\n\n"
    "4. Demon Slayer\n"
    "   Best animation quality + emotional storytelling.\n\n"
    "5. Steins;Gate\n"
    "   The best sci-fi anime ever made. Slow start, incredible payoff.\n\n"
    "6. Hunter x Hunter (2011)\n"
    "   Every arc outdoes the last. A true masterpiece.\n\n"
    "7. One Punch Man\n"
    "   Hilarious, action-packed, and surprisingly deep.\n\n"
    "8. Your Lie in April\n"
    "   Beautiful music, emotional story. Will make you cry.\n\n"
    "9. Code Geass\n"
    "   Strategy, politics, and one of anime's greatest endings.\n\n"
    "10. Spirited Away (Movie)\n"
    "    Studio Ghibli's masterpiece. A perfect film.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Use /search <title> for details on any of these.\n"
    "Use /beginner for a full category breakdown."
)


async def beginner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(BEGINNER_TEXT)


async def starterpack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(STARTERPACK_TEXT)


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/recommend <anime>       — Shows similar to one you love\n"
            "/recommend <genre>       — Top picks in a genre\n"
            "/recommend anime like X  — Same as above\n\n"
            "Examples:\n"
            "  /recommend death note\n"
            "  /recommend anime like attack on titan\n"
            "  /recommend romance\n"
            "  /recommend dark fantasy"
        )
        return

    query = " ".join(context.args).lower().strip()

    # Handle "anime like X" pattern
    like_match = re.match(r"(?:anime\s+)?(?:like|similar to|similar)\s+(.+)", query)
    if like_match:
        query = like_match.group(1).strip()

    genre_id = GENRE_MAP.get(query)

    if genre_id:
        # Genre mode: deduplicated top anime for that genre
        try:
            r = requests.get(
                "https://api.jikan.moe/v4/anime",
                params={"genres": genre_id, "order_by": "score", "sort": "desc", "limit": 25},
                timeout=10,
            )
            results = r.json().get("data", [])
            if not results:
                await update.message.reply_text(f"No recommendations found for '{query.title()}'.")
                return

            seen_keys: set[str] = set()
            diverse: list = []
            for anime in results:
                key = _franchise_key(anime.get("title", ""))
                if key not in seen_keys:
                    seen_keys.add(key)
                    diverse.append(anime)
                if len(diverse) == 10:
                    break

            lines = [f"🎯 Top {query.title()} Picks\n"]
            for i, anime in enumerate(diverse, start=1):
                title = anime.get("title", "N/A")
                score = anime.get("score") or "N/A"
                episodes = anime.get("episodes") or "Ongoing"
                lines.append(f"{i}. {title}\n   ⭐ {score} | 📺 {episodes} eps")

            await update.message.reply_text("\n\n".join(lines))
        except Exception:
            await update.message.reply_text("Something went wrong. Please try again.")
    else:
        # Anime mode: Jikan recommendations based on the title
        try:
            r = requests.get(
                "https://api.jikan.moe/v4/anime",
                params={"q": query, "limit": 1},
                timeout=10,
            )
            results = r.json().get("data", [])
            if not results:
                await update.message.reply_text(
                    "Anime not found.\n\n"
                    "Try a genre instead:\n"
                    "/recommend action\n"
                    "/recommend romance\n"
                    "/recommend mystery"
                )
                return

            anime = results[0]
            anime_id = anime["mal_id"]
            anime_title = anime.get("title", "N/A")

            r2 = requests.get(
                f"https://api.jikan.moe/v4/anime/{anime_id}/recommendations",
                timeout=10,
            )
            recs = r2.json().get("data", [])[:10]

            if not recs:
                await update.message.reply_text(
                    f"No recommendations found for {anime_title}.\n"
                    "Try /similar for an alternative approach."
                )
                return

            lines = [f"🎯 If you liked {anime_title}...\n"]
            for i, rec in enumerate(recs, start=1):
                entry = rec.get("entry", {})
                title = entry.get("title", "N/A")
                lines.append(f"🎌 {i}. {title}")

            await update.message.reply_text("\n".join(lines))
        except Exception:
            await update.message.reply_text("Something went wrong. Please try again.")


# ── Persistence Helpers ────────────────────────────────────────────────────

STATUS_LABELS: dict[str, str] = {
    "watching":   "📺 Watching",
    "completed":  "✅ Completed",
    "planned":    "📝 Planned",
    "dropped":    "❌ Dropped",
}


def load_watchlist() -> dict:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_watchlist(data: dict) -> None:
    WATCHLIST_FILE.write_text(json.dumps(data, indent=2))


def load_profiles() -> dict:
    if PROFILES_FILE.exists():
        try:
            return json.loads(PROFILES_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_profiles(data: dict) -> None:
    PROFILES_FILE.write_text(json.dumps(data, indent=2))


def update_profile(
    user_id: int,
    username: str | None,
    command: str | None = None,
    genre: str | None = None,
    anime_search: bool = False,
    manga_search: bool = False,
) -> None:
    profiles = load_profiles()
    uid = str(user_id)
    if uid not in profiles:
        profiles[uid] = {
            "join_date": datetime.now().strftime("%Y-%m-%d"),
            "username": username or "Unknown",
            "anime_searched": 0,
            "manga_searched": 0,
            "commands_used": {},
            "genre_searches": {},
        }
    p = profiles[uid]
    if username:
        p["username"] = username
    if command:
        p["commands_used"][command] = p["commands_used"].get(command, 0) + 1
    if genre:
        p["genre_searches"][genre] = p["genre_searches"].get(genre, 0) + 1
    if anime_search:
        p["anime_searched"] = p.get("anime_searched", 0) + 1
    if manga_search:
        p["manga_searched"] = p.get("manga_searched", 0) + 1
    save_profiles(profiles)


# ── Watchlist ──────────────────────────────────────────────────────────────

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args or []

    data = load_watchlist()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {s: [] for s in STATUS_LABELS}
    user_wl = data[uid]

    if not args:
        total = sum(len(v) for v in user_wl.values())
        if total == 0:
            await update.message.reply_text(
                "Your watchlist is empty!\n\n"
                "Add anime with:\n"
                "/watchlist add <anime> watching\n"
                "/watchlist add <anime> planned\n"
                "/watchlist add <anime> completed"
            )
            return
        lines = ["📋 Your Watchlist\n"]
        for status, label in STATUS_LABELS.items():
            entries = user_wl.get(status, [])
            if entries:
                lines.append(f"{label} ({len(entries)})")
                for e in entries[:10]:
                    lines.append(f"  • {e}")
                if len(entries) > 10:
                    lines.append(f"  ... and {len(entries) - 10} more")
        await update.message.reply_text("\n".join(lines))
        return

    subcommand = args[0].lower()

    # /watchlist <status> → show that category
    if subcommand in STATUS_LABELS and len(args) == 1:
        entries = user_wl.get(subcommand, [])
        label = STATUS_LABELS[subcommand]
        if not entries:
            await update.message.reply_text(f"{label}: Nothing here yet.")
            return
        lines = [f"{label} ({len(entries)})\n"]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e}")
        await update.message.reply_text("\n".join(lines))
        return

    # /watchlist add <anime> [status]
    if subcommand == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /watchlist add <anime> [watching|completed|planned|dropped]\n"
                "Default: planned"
            )
            return
        if args[-1].lower() in STATUS_LABELS and len(args) > 2:
            status = args[-1].lower()
            anime_name = " ".join(args[1:-1])
        else:
            status = "planned"
            anime_name = " ".join(args[1:])

        for s in STATUS_LABELS:
            for existing in user_wl.get(s, []):
                if existing.lower() == anime_name.lower():
                    await update.message.reply_text(
                        f"'{anime_name}' is already in your {s} list.\n"
                        f"Use /watchlist remove {anime_name} first."
                    )
                    return

        user_wl.setdefault(status, []).append(anime_name)
        data[uid] = user_wl
        save_watchlist(data)
        await update.message.reply_text(f"Added '{anime_name}' to {STATUS_LABELS[status]}.")
        return

    # /watchlist remove <anime>
    if subcommand == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: /watchlist remove <anime>")
            return
        anime_name = " ".join(args[1:])
        removed_from = None
        for s in list(STATUS_LABELS.keys()):
            lst = user_wl.get(s, [])
            for entry in list(lst):
                if entry.lower() == anime_name.lower():
                    lst.remove(entry)
                    removed_from = STATUS_LABELS[s]
                    break
            if removed_from:
                break

        if removed_from:
            data[uid] = user_wl
            save_watchlist(data)
            await update.message.reply_text(f"Removed '{anime_name}' from {removed_from}.")
        else:
            await update.message.reply_text(f"'{anime_name}' not found in your watchlist.")
        return

    await update.message.reply_text(
        "Watchlist commands:\n"
        "/watchlist — Show full list\n"
        "/watchlist add <anime> [watching|completed|planned|dropped]\n"
        "/watchlist remove <anime>\n"
        "/watchlist watching\n"
        "/watchlist completed\n"
        "/watchlist planned\n"
        "/watchlist dropped"
    )


# ── Profile & Stats ────────────────────────────────────────────────────────

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uid = str(user.id)
    username = user.username or user.first_name or "Unknown"

    profiles = load_profiles()
    p = profiles.get(uid, {})

    wl_data = load_watchlist()
    user_wl = wl_data.get(uid, {})
    total_tracked = sum(len(v) for v in user_wl.values())

    fav_data = load_favorites()
    fav_count = len(fav_data.get(uid, []))

    join_date = p.get("join_date", "Unknown")
    anime_searched = p.get("anime_searched", 0)
    manga_searched = p.get("manga_searched", 0)
    commands = p.get("commands_used", {})
    genre_searches = p.get("genre_searches", {})

    top_commands = sorted(commands.items(), key=lambda x: x[1], reverse=True)[:3]
    top_genres = sorted(genre_searches.items(), key=lambda x: x[1], reverse=True)[:3]
    activity_score = (anime_searched * 2) + (manga_searched * 2) + total_tracked + sum(commands.values())

    lines = [f"👤 {username}'s Profile\n"]
    lines.append(f"📅 Member since: {join_date}")
    lines.append(f"🔍 Anime searched: {anime_searched}")
    lines.append(f"📚 Manga searched: {manga_searched}")
    lines.append(f"📺 Anime tracked: {total_tracked}")
    lines.append(f"⭐ Favourites: {fav_count}")
    if top_genres:
        lines.append(f"🎭 Top genres: {', '.join(g.title() for g, _ in top_genres)}")
    if top_commands:
        lines.append(f"🔥 Most used: {', '.join(f'/{c}' for c, _ in top_commands)}")
    lines.append(f"⚡ Activity score: {activity_score}")

    wl_items = []
    for s in ["watching", "completed", "planned", "dropped"]:
        n = len(user_wl.get(s, []))
        if n:
            wl_items.append(f"{STATUS_LABELS[s]}: {n}")
    if wl_items:
        lines.append("\n📋 Watchlist:")
        lines.extend(wl_items)

    await update.message.reply_text("\n".join(lines))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_cmd(update, context)


# ── Manga System ───────────────────────────────────────────────────────────

MANGA_GENRE_MAP: dict[str, int] = {
    "action": 1, "adventure": 2, "comedy": 4, "drama": 8,
    "fantasy": 10, "horror": 14, "mystery": 7, "romance": 22,
    "sci-fi": 24, "scifi": 24, "science fiction": 24,
    "slice of life": 36, "sports": 30, "supernatural": 37,
    "thriller": 41, "psychological": 40, "historical": 13,
    "shounen": 27, "shoujo": 25, "seinen": 42, "josei": 43,
}


async def manga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /manga <title>\nExample: /manga berserk")
        return
    query = " ".join(context.args)
    try:
        update_profile(update.effective_user.id, update.effective_user.username, command="manga", manga_search=True)
    except Exception:
        pass
    try:
        r = requests.get("https://api.jikan.moe/v4/manga", params={"q": query, "limit": 1}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Manga not found. Check the spelling and try again.")
            return
        m = results[0]
        title = m.get("title", "N/A")
        title_en = m.get("title_english") or ""
        title_jp = m.get("title_japanese") or ""
        chapters = m.get("chapters") or "N/A"
        volumes = m.get("volumes") or "N/A"
        score = m.get("score") or "N/A"
        rank = m.get("rank") or "N/A"
        status = m.get("status", "N/A")
        genres = ", ".join(g["name"] for g in m.get("genres", [])[:5]) or "N/A"
        synopsis = m.get("synopsis") or ""
        if len(synopsis) > 800:
            synopsis = synopsis[:800] + "..."
        cover = m.get("images", {}).get("jpg", {}).get("large_image_url")
        authors = ", ".join(a.get("name", "") for a in m.get("authors", [])[:2]) or "N/A"
        serialization = ", ".join(s.get("name", "") for s in m.get("serializations", [])[:2]) or None

        lines = [f"📚 {title}"]
        if title_en and title_en != title:
            lines.append(f"🇬🇧 {title_en}")
        if title_jp:
            lines.append(f"🇯🇵 {title_jp}")
        lines.append("")
        lines.append(f"⭐ Score: {score}  |  🏆 Rank: #{rank}")
        lines.append(f"📖 Chapters: {chapters}  |  📕 Volumes: {volumes}")
        lines.append(f"📌 Status: {status}")
        lines.append(f"✍️ Author: {authors}")
        if serialization:
            lines.append(f"📰 Magazine: {serialization}")
        lines.append(f"🎭 Genres: {genres}")
        if synopsis:
            lines.append(f"\n📝 Synopsis:\n{synopsis}")

        caption = "\n".join(lines)
        if cover:
            try:
                await update.message.reply_photo(photo=cover, caption=caption[:1024])
                if len(caption) > 1024:
                    await update.message.reply_text(caption[1024:])
                return
            except Exception:
                pass
        await update.message.reply_text(caption)
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


async def topmanga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = requests.get("https://api.jikan.moe/v4/top/manga", params={"limit": 10}, timeout=10)
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Could not fetch top manga. Please try again.")
            return
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = ["📚 Top 10 Manga of All Time\n"]
        for i, m in enumerate(results, 1):
            medal = medals.get(i, f"{i}.")
            title = m.get("title", "N/A")
            score = m.get("score") or "N/A"
            chapters = m.get("chapters") or "Ongoing"
            lines.append(f"{medal} {title}\n   ⭐ {score} | 📖 {chapters} ch")
        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


async def randommanga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = requests.get("https://api.jikan.moe/v4/random/manga", timeout=10)
        m = r.json().get("data", {})
        if not m:
            await update.message.reply_text("Could not fetch a random manga. Please try again.")
            return
        title = m.get("title", "N/A")
        score = m.get("score") or "N/A"
        chapters = m.get("chapters") or "N/A"
        volumes = m.get("volumes") or "N/A"
        status = m.get("status", "N/A")
        genres = ", ".join(g["name"] for g in m.get("genres", [])[:4]) or "N/A"
        synopsis = m.get("synopsis") or ""
        if len(synopsis) > 500:
            synopsis = synopsis[:500] + "..."
        cover = m.get("images", {}).get("jpg", {}).get("large_image_url")
        lines = [
            "🎲 Random Manga Pick\n",
            f"📚 {title}",
            f"⭐ {score}  |  📖 {chapters} ch  |  📕 {volumes} vol",
            f"📌 {status}",
            f"🎭 {genres}",
        ]
        if synopsis:
            lines.append(f"\n📝 {synopsis}")
        caption = "\n".join(lines)
        if cover:
            try:
                await update.message.reply_photo(photo=cover, caption=caption[:1024])
                return
            except Exception:
                pass
        await update.message.reply_text(caption)
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


async def mangagenre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        supported = ", ".join(sorted(k for k in MANGA_GENRE_MAP if k not in ("scifi", "science fiction")))
        await update.message.reply_text(
            f"Usage: /mangagenre <genre>\nExample: /mangagenre romance\n\nSupported:\n{supported}"
        )
        return
    query = " ".join(context.args).lower().strip()
    genre_id = MANGA_GENRE_MAP.get(query)
    if not genre_id:
        supported = ", ".join(sorted(k for k in MANGA_GENRE_MAP if k not in ("scifi", "science fiction")))
        await update.message.reply_text(f"Genre '{query}' not recognised.\n\nSupported:\n{supported}")
        return
    try:
        r = requests.get(
            "https://api.jikan.moe/v4/manga",
            params={"genres": genre_id, "order_by": "score", "sort": "desc", "limit": 10},
            timeout=10,
        )
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text(f"No manga found for '{query.title()}'.")
            return
        lines = [f"📚 Top {query.title()} Manga\n"]
        for i, m in enumerate(results[:8], 1):
            title = m.get("title", "N/A")
            score = m.get("score") or "N/A"
            chapters = m.get("chapters") or "?"
            lines.append(f"{i}. {title}\n   ⭐ {score} | 📖 {chapters} ch")
        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


# ── Dub Availability ───────────────────────────────────────────────────────

async def dub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /dub <anime>\nExample: /dub attack on titan")
        return
    query = " ".join(context.args)
    try:
        result = anilist("""
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    title { romaji english }
    characters(sort: [ROLE], page: 1, perPage: 6) {
      edges {
        voiceActors(sort: RELEVANCE) {
          name { full }
          language
        }
      }
    }
    externalLinks { url site type }
  }
}
        """, {"search": query})
        media = result.get("data", {}).get("Media")
        if not media:
            await update.message.reply_text("Anime not found.")
            return
        title = media["title"].get("english") or media["title"].get("romaji", "N/A")

        all_languages: set[str] = set()
        for edge in media.get("characters", {}).get("edges", []):
            for va in edge.get("voiceActors", []):
                lang = va.get("language", "")
                if lang:
                    all_languages.add(lang.title())

        ext_links = media.get("externalLinks", [])
        streaming = list({lnk["site"] for lnk in ext_links
                          if lnk.get("type") == "STREAMING" and lnk.get("site") in STREAMING_SITES})

        lines = [f"🎙️ Dub Info — {title}\n"]
        if all_languages:
            lines.append("🗣️ Voice acted in:")
            lang_emoji = {
                "Japanese": "🇯🇵", "English": "🇬🇧", "Spanish": "🇪🇸",
                "Portuguese": "🇧🇷", "French": "🇫🇷", "German": "🇩🇪",
                "Italian": "🇮🇹", "Korean": "🇰🇷", "Chinese": "🇨🇳",
            }
            priority = ["Japanese", "English", "Spanish", "Portuguese", "French", "German", "Italian", "Korean"]
            sorted_langs = sorted(all_languages, key=lambda l: priority.index(l) if l in priority else 99)
            for lang in sorted_langs:
                lines.append(f"  {lang_emoji.get(lang, '🌐')} {lang}")
        else:
            lines.append("⚠️ Language data not available for this title.")

        if streaming:
            lines.append(f"\n📡 Streaming on: {', '.join(streaming[:5])}")

        lines.append("\nNote: Hindi/Tamil/Telugu dubs may be available on regional")
        lines.append("platforms (Ani-One Asia, Sony LIV, etc.) — check locally.")

        await update.message.reply_text("\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


# ── Upcoming Anime ─────────────────────────────────────────────────────────

async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = requests.get(
            "https://api.jikan.moe/v4/seasons/upcoming",
            params={"limit": 25},
            timeout=10,
        )
        results = r.json().get("data", [])
        if not results:
            await update.message.reply_text("Could not fetch upcoming anime. Please try again.")
            return
        top10 = sorted(results, key=lambda a: a.get("members") or 0, reverse=True)[:10]
        lines = ["📅 Most Anticipated Upcoming Anime\n"]
        for i, anime in enumerate(top10, 1):
            title = anime.get("title", "N/A")
            studios = ", ".join(s.get("name", "") for s in anime.get("studios", [])[:1]) or "TBA"
            episodes = anime.get("episodes") or "TBA"
            members = anime.get("members") or 0
            season_name = (anime.get("season") or "").title()
            year = anime.get("year") or ""
            date_str = f"{season_name} {year}".strip() if (season_name or year) else "TBA"
            lines.append(
                f"{i}. {title}\n"
                f"   🏢 {studios}  |  📺 {episodes} eps  |  📆 {date_str}\n"
                f"   👥 {members:,} tracking"
            )
        await update.message.reply_text("\n\n".join(lines))
    except Exception:
        await update.message.reply_text("Something went wrong. Please try again.")


async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ai <question>  — ask Ani Zeo's AI anything about anime.

    Routes through the configured provider chain (Gemini → GLM → NVIDIA NIM).
    The command works independently of ENABLE_AI_CHAT.
    """
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "🤖 Ask me anything about anime!\n\n"
            "Usage: /ai <your question>\n\n"
            "Examples:\n"
            "  /ai recommend anime like Death Note\n"
            "  /ai what is the best mecha anime?\n"
            "  /ai explain the ending of Evangelion\n"
            "  /ai compare Attack on Titan and Demon Slayer"
        )
        return

    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Please include a question after /ai.")
        return

    await update.message.chat.send_action("typing")

    try:
        response = await _ai_router.route(prompt=query)
    except Exception:
        await update.message.reply_text(
            "Something went wrong with the AI. Please try again shortly."
        )
        return

    if response.success and response.text:
        await update.message.reply_text(response.text)
    else:
        await update.message.reply_text(
            "AI is temporarily unavailable. Please try again in a moment."
        )


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    # Guide
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("beginner", beginner))
    app.add_handler(CommandHandler("starterpack", starterpack))
    app.add_handler(CommandHandler("recommend", recommend))

    # Anime search & info
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("similar", similar))
    app.add_handler(CommandHandler("compare", compare))
    app.add_handler(CommandHandler("trailer", trailer))
    app.add_handler(CommandHandler("dub", dub))

    # Manga system
    app.add_handler(CommandHandler("manga", manga))
    app.add_handler(CommandHandler("topmanga", topmanga))
    app.add_handler(CommandHandler("randommanga", randommanga))
    app.add_handler(CommandHandler("mangagenre", mangagenre))

    # Profile & tracking
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))

    # Characters & studios
    app.add_handler(CommandHandler("character", character))
    app.add_handler(CommandHandler("studio", studio))

    # Rankings
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("genre", genre))

    # Seasonal
    app.add_handler(CommandHandler("season", season))
    app.add_handler(CommandHandler("upcoming", upcoming))
    app.add_handler(CommandHandler("airing", airing))
    app.add_handler(CommandHandler("schedule", schedule_cmd))

    # Discovery
    app.add_handler(CommandHandler("random", random_anime))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("quiz", quiz))

    # Favourites
    app.add_handler(CommandHandler("favorite", favorite_cmd))
    app.add_handler(CommandHandler("favorites", favorites_cmd))

    # AI chat
    app.add_handler(CommandHandler("ai", ai_cmd))

    # News
    app.add_handler(CommandHandler("news", news))

    app.add_handler(CallbackQueryHandler(quiz_callback, pattern=r"^quiz:"))
    app.add_handler(CallbackQueryHandler(cmd_callback, pattern=r"^cmd:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message), group=1)

    print("Ani Zeo v3.0 is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
