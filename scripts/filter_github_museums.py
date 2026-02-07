#!/usr/bin/env python3
"""
Filter GitHub museum candidates to actual museums with meaningful activity.
Reads github_museum_details.json, applies filtering, outputs curated list.
"""

import sys
import io
import json
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

DETAILS_FILE = os.path.join(os.path.dirname(__file__), "github_museum_details.json")
CURATED_FILE = os.path.join(os.path.dirname(__file__), "github_museums_curated.json")

# Orgs that are clearly NOT museums/cultural institutions despite matching search
# (software companies, student projects, NFT/crypto, gaming, personal archives, etc.)
EXCLUDE = {
    # Software/tech companies that serve museums but aren't museums
    "ixc", "k-int", "mapado", "ideesculture", "fluxguide", "NeoTecDigital",
    "digitalwarenkombinat", "exhibitionist-digital", "conlect", "histify",
    "GulfStreamJS", "The-Museum-Platform", "museum-digital", "desmusea",
    "museotechniki", "chartmuseum",  # Helm chart museum, not a real museum

    # Gaming / not real museums
    "GTNH-Museum",  # Minecraft mod
    "Team-ARG-Museum",  # Arduboy game archive
    "The-Water-Museum",  # Game/art project
    "ArtheonVR",  # VR app company
    "museum-repos",  # Generic placeholder
    "museumWorld",  # Generic
    "nto-final",  # Student project
    "obsolete-code-museum",  # Code archive, not a museum
    "ByteMuseum",  # Personal project graveyard
    "RaMuseum",  # Personal collection
    "alexcloudstar-museum",  # Personal old projects
    "museoa",  # Code archive
    "musxum",  # Personal archive
    "mudmuseum",  # Unclear/inactive
    "rosesinthemath",  # Not a museum
    "FurShows",  # Furry streaming, not museum
    "MuseumMonitoring",  # Monitoring tool, not museum
    "Pimuseum",  # Not a real museum
    "Museumify",  # App project
    "Museum-Mate",  # App project
    "Museum-Recommendations",  # App project
    "museumTSPK63",  # Student project
    "museumvisit",  # App
    "MuseumSite",  # Generic
    "Museumproject-Placeholder",  # Placeholder
    "museumsbahn-it-community",  # Railway hobby
    "museum-app",  # Generic app
    "museum-plus",  # Generic
    "museum-of-nifty-art",  # NFT
    "museum-of-war",  # NFT project
    "museumor",  # VR project
    "People-Museum-Project",  # Student project
    "MuseumofScienceFiction",  # Concept, not operational
    "museumofthebible",  # Minimal presence
    "fabulous-museum",  # Generic
    "cloud-museum",  # AI site generator
    "ismuseum",  # Virtual museum concept
    "Museolab",  # Generic
    "museoproject",  # Generic
    "museorosasbotran",  # Personal
    "MuseoMixBO",  # Event
    "museopeli",  # Finnish: "museum game"
    "museofficial",  # Not a museum
    "museofmetal3019",  # Not a museum
    "Museo16601",  # Unknown
    "Museo-Light",  # Not a museum
    "Museo-del-Canal-Proyectos",  # Minimal
    "museogodofoundation",  # Unclear
    "museoXela",  # Software project
    "MuseoInteractivoRuralItinerante",  # Minimal
    "MuseoPapalote", "Museo-Papalote",  # Duplicate/minimal
    "MuseoRealAlto",  # Minimal

    # NFT / crypto galleries
    "mocaOS", "ColorMuseum", "herrgallery", "Bright-Moments",
    "alpha-sol", "CryptoSI-Gallery", "vivid-gallery", "Gradient-Art-Market",
    "artii-foundation", "artii-korea", "Spicaro-orga", "VayerArt-Gallery",
    "ArtyVinci", "the-memery", "YaDiGGiT",

    # Personal art galleries / portfolios
    "artur-basak-art", "leonardosiu", "pelaezochoa", "shilyaeva-art",
    "mindandmill", "pankegallery", "ScreenSaverGallery",
    "The-Hidden-Gallery", "Wilhelmina-s-Art-Gallery", "CSS-ART-GALLERY",
    "Art-Boutique", "caryartgallery", "exhibition-gallery",

    # Student/class projects named "biblioteka"
    "BiblioteKA-Ag31", "BiblioteKA-BackEnd", "BiblioteKA-G3",
    "BiblioteKA-Grupo-18", "BiblioteKA-Grupo33", "BiblioteKA-grupo44",
    "biblioteka-M5", "BiblioteKa-M5-group18", "BiblioteKA-m5-t15-g18",
    "Biblioteka2025", "bibliotekaM5ProjetoFinal", "bibliotekata",
    "biblioteka-team", "biblioteko-app",

    # Academic/research groups (not museums themselves)
    "scholarslab",  # University lab
    "ELTE-DH",  # University dept
    "arthur-schnitzler", "hermann-bahr",  # Author archives at academy
    "DigitalHumanitiesCraft",  # Software company
    "MSU-DHI-Lab",  # University lab
    "PerceptionRobotique",  # Robotics lab
    "JRG-DH",  # Junior research group
    "IDCH",  # Institute
    "ITU-MBL-heritage",  # University course
    "DHL-NYUSH",  # University lab
    "uniba-dthc",  # University chair
    "ValuesForwardPraxis",  # Resource list
    "DARE-lab",  # Research lab
    "PROV-DCH",  # Standard

    # Too generic / not clearly a museum org
    "OnlineArtGallery-SEP490-SP25-SE11",  # Student project
    "Green-Team-D",  # Student project
    "mobileArtMuseumY",  # App project
    "curat-harvard-museum",  # Student project
    "CMJ-AG",  # Student group
    "Emu-gators",  # Student project
    "Mawruth",  # App project
    "MicroMegArt",  # Research
    "PatternCraft",  # Art project
    "soliddifference",  # Furniture company
    "8amt",  # Heritage game
    "sgm-projects",  # Geological museum projects

    # Cultural heritage orgs (not museums per se, but keep borderline ones)
    # Keeping: europeana, netwerk-digitaal-erfgoed, dpla, AI4LAM, sucho-archiving
    "GeoRiskA",  # Research group
    "BelliniDigitalCorrespondence",  # Digital edition
    "enriching-digital-heritage",  # Workshop
    "heritage-observatory",  # Crowdsourcing project
    "DigitalHeritage",  # Generic
    "Digital-Heritage-Lab",  # Company
    "Bali-Digital-Heritage",  # Initiative
    "DHARMA3D",  # University research
    "project-tirtha",  # Research project
    "The-DHP-Platform",  # Platform
    "globaldigitalheritage",  # Organization
    "WCHArchives",  # Org
    "SJCHeritagePubOps",  # Publishing team
    "open-mool",  # Heritage project

    # Software for museums (tools, not museums)
    "ArctosDB",  # Collection management software
    "specify",  # Collection management software
    "kitodo",  # Digitization software
    "eaasi",  # Emulation framework
    "emil-emulation",  # Emulation framework
    "nahpu",  # Field catalog app

    # Minimal presence (1 repo, no clear identity)
    "Art-for-All-Taiwan", "elhi-org", "Image-Permanence-Institute",
    "ludimuseo", "MuPreDi", "Museo-Nacional", "museologia",
    "Museology-Project", "open-museum", "ZooMu", "Museosovellus",
    "Museos-Madrid", "Buenos-Aires-Museo",

    # Libraries (not museums)
    "scriptotek", "kbib", "ldbib", "Biblioteksvagten", "Biblioteksbanden",
    "bibliotek", "biblioteksentralen", "esbjergbib", "statsbiblioteket",

    # Deprecated / duplicates
    "det-kgl-bibliotek",  # Old, replaced by kb-dk
    "sfomuseum-data",  # Data sub-org of sfomuseum
    "amnh-library",  # Library sub-org of amnh
    "Thomas-J-Watson-Library",  # Library at Met (Met already included)
    "Computer-history-Museum",  # Duplicate source code archive

    # Events / hackathons / projects (not museums)
    "museomix", "MuseomixCH",  # Museum hackathon events
    "artificialmuseum",  # Virtual art concept project
    "museuminabox",  # Product/project
    "tanc-ahrc",  # Research programme
    "sucho-archiving",  # Archiving project
    "AI4LAM",  # Community org
    "gbhl",  # Digital library
    "dpla",  # Digital library
    "Bibliohack",  # Tech for libraries
    "DigitalibraryItaly",  # Digital library
    "ncdhc",  # Digital heritage center
    "indic-archive",  # Digital archive foundation
    "qirimca",  # Language preservation NGO
    "AiWA-Ai-West-Africa",  # Cultural tech institute
    "DHILab-LE",  # Research lab
    "maythiwat-archive",  # "kinda museum or garbage pile"

    # Research labs at museums (parent org already included)
    "de-Medeiros-insect-lab",  # Lab at Field Museum
    "reelab",  # Lab at Field Museum
    "TU-NHM",  # Research group at Tartu
    "arttracks",  # Software project at Carnegie Museum
    "BNHM",  # Consortium at Berkeley
    "MCZbase",  # Dept at Harvard
    "flmnh-ai",  # Lab at Florida Museum
    "FLMNH-Informatics",  # Dept at Florida Museum
    "FLMNH",  # Office at Florida Museum
    "museum-of-vertebrate-zoology",  # Dept at Berkeley
    "centrofermi",  # Research center

    # Unclear / very small / not clearly museum tech
    "Art2u",  # Unclear Danish org
    "museonum",  # Unclear
    "the-chain-museum",  # Unclear
    "artmuseo",  # Equity ecosystem, not a museum
    "malariamuseum",  # Very niche
    "museotazzetti",  # Minimal
    "museo3tetti",  # Minimal
    "alianzacolombianademuseos",  # Association, not museum
    "Tin-Marin",  # Minimal
    "MuChiTico",  # Minimal
    "BolinasMuseum",  # Minimal
    "InterferenceArchive",  # Archive, not museum
    "arbark-se",  # Archive, not museum
    "museoXela",
    "bourbon-museum",
    "Calmigration",
    "KununurraMuseum",
    "monticello-railway-museum",
    "TrolleyMuseum",
    "Comic-Con-Museum",
    "ism-feedback",
    "NSM-ITM",
    "museumofthefuture",  # UAE museum, minimal repos
}


def main():
    with open(DETAILS_FILE, "r", encoding="utf-8") as f:
        all_orgs = json.load(f)

    # Filter
    curated = []
    excluded_names = []
    for org in all_orgs:
        login = org["login"]
        repos = org["public_repos"]

        # Skip excluded
        if login in EXCLUDE:
            excluded_names.append(login)
            continue

        # Skip zero repos
        if repos == 0:
            continue

        curated.append(org)

    # Sort by repo count
    curated.sort(key=lambda x: -x["public_repos"])

    # Save curated list
    with open(CURATED_FILE, "w", encoding="utf-8") as f:
        json.dump(curated, f, indent=2, ensure_ascii=False)

    # Print
    print(f"{'='*70}")
    print(f"CURATED MUSEUM GITHUB ORGANIZATIONS ({len(curated)} orgs)")
    print(f"{'='*70}")
    print(f"Total candidates: {len(all_orgs)}")
    print(f"Excluded: {len(excluded_names)}")
    print(f"Curated: {len(curated)}")
    print()

    for d in curated:
        repos = d["public_repos"]
        name = d["name"] if d["name"] != d["login"] else ""
        location = d.get("location", "")
        desc = d.get("description", "")
        web = d.get("blog", "")

        line = f"  {d['login']} ({repos} repos)"
        if name:
            line += f" - {name}"
        if location:
            line += f" [{location}]"
        print(line)
        if desc:
            print(f"    {desc}")
        if web:
            print(f"    {web}")
        print()

    print(f"\nSaved {len(curated)} curated orgs to {CURATED_FILE}")


if __name__ == "__main__":
    main()
