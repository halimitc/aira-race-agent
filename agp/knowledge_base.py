import json
from typing import List, Dict, Any
from logger import logger
from prompts import SYSTEM_CANDIDATE_GENERATION, USER_CANDIDATE_GEN_TEMPLATE
from agp.reasoning_provider import ReasoningProvider
from agp.cache import cache

class HybridKnowledgeBase:
    """Layered knowledge base providing candidate lists from Cache, Local DB, and LLMs."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider
        # Local offline database for basic categories
        self.local_offline_db: Dict[str, List[str]] = {
            "country": [
                "United States", "United Kingdom", "Canada", "Germany", "France", "Japan", "China", "India",
                "Brazil", "Australia", "Russia", "Italy", "Spain", "South Korea", "Mexico", "Indonesia",
                "Saudi Arabia", "South Africa", "Argentina", "Egypt", "Nigeria", "Singapore", "New Zealand",
                "Sweden", "Norway", "Switzerland", "Netherlands", "Turkey", "Vietnam", "Thailand"
            ],
            "animal": [
                "Lion", "Tiger", "Elephant", "Giraffe", "Zebra", "Bear", "Wolf", "Fox", "Rabbit", "Deer",
                "Kangaroo", "Koala", "Panda", "Cheetah", "Leopard", "Dolphin", "Whale", "Shark", "Eagle", "Owl",
                "Penguin", "Crocodile", "Snake", "Frog", "Monkey", "Chimpanzee", "Gorilla", "Horse", "Cow", "Dog"
            ],
            "fruit": [
                "Apple", "Banana", "Orange", "Strawberry", "Grape", "Mango", "Pineapple", "Watermelon", "Peach",
                "Cherry", "Blueberry", "Raspberry", "Lemon", "Lime", "Plum", "Pear", "Avocado", "Kiwi", "Coconut"
            ],
            "planet": [
                "Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"
            ],
            "city": [
                "New York", "London", "Tokyo", "Paris", "Sydney", "Berlin", "Moscow", "Beijing", "Dubai",
                "Los Angeles", "Chicago", "Toronto", "Mumbai", "Shanghai", "Istanbul", "Rome", "Bangkok",
                "Cairo", "Rio de Janeiro", "Buenos Aires", "Seoul", "Singapore", "Hong Kong", "Madrid",
                "Amsterdam", "Vienna", "Prague", "Lisbon", "Stockholm", "Athens"
            ],
            "movie": [
                "The Godfather", "Titanic", "The Shawshank Redemption", "Forrest Gump", "The Dark Knight",
                "Inception", "Pulp Fiction", "The Matrix", "Schindler's List", "Star Wars",
                "Jurassic Park", "The Lion King", "Gladiator", "Avatar", "Interstellar",
                "Fight Club", "The Lord of the Rings", "Jaws", "The Silence of the Lambs", "Casablanca",
                "Back to the Future", "Goodfellas", "Rocky", "Psycho", "Alien",
                "The Wizard of Oz", "E.T. the Extra-Terrestrial", "Toy Story", "Frozen", "Black Panther"
            ],
            "person": [
                "Albert Einstein", "Leonardo da Vinci", "William Shakespeare", "Mahatma Gandhi",
                "Martin Luther King Jr.", "Nelson Mandela", "Isaac Newton", "Marie Curie",
                "Abraham Lincoln", "Cleopatra", "Napoleon Bonaparte", "Alexander the Great",
                "Queen Elizabeth II", "Winston Churchill", "Nikola Tesla", "Charles Darwin",
                "Aristotle", "Plato", "Confucius", "Mozart", "Beethoven", "Picasso",
                "Elon Musk", "Steve Jobs", "Oprah Winfrey", "Michael Jordan", "Muhammad Ali",
                "Marilyn Monroe", "Elvis Presley", "Princess Diana"
            ],
            "book": [
                "To Kill a Mockingbird", "1984", "Pride and Prejudice", "The Great Gatsby",
                "Harry Potter and the Sorcerer's Stone", "The Catcher in the Rye", "Lord of the Flies",
                "Animal Farm", "Brave New World", "The Hobbit", "Moby Dick", "War and Peace",
                "Crime and Punishment", "The Odyssey", "Don Quixote", "Jane Eyre", "Wuthering Heights",
                "Frankenstein", "Dracula", "The Divine Comedy", "Great Expectations",
                "One Hundred Years of Solitude", "The Alchemist", "Hamlet", "Romeo and Juliet",
                "A Tale of Two Cities", "Les Miserables", "The Count of Monte Cristo",
                "The Chronicles of Narnia", "Dune"
            ],
            "song": [
                "Bohemian Rhapsody", "Imagine", "Hotel California", "Stairway to Heaven",
                "Like a Rolling Stone", "Yesterday", "Smells Like Teen Spirit", "Billie Jean",
                "Hey Jude", "Let It Be", "What a Wonderful World", "Thriller", "Purple Rain",
                "Respect", "My Way", "Sweet Child O' Mine", "Hallelujah", "Wonderwall",
                "Rolling in the Deep", "Shape of You", "Despacito", "Uptown Funk",
                "Old Town Road", "Blinding Lights", "Somebody That I Used to Know",
                "Happy", "Bad Guy", "Lose Yourself", "Under Pressure", "Dancing Queen"
            ],
            "music": [
                "Bohemian Rhapsody", "Imagine", "Hotel California", "Stairway to Heaven",
                "Like a Rolling Stone", "Yesterday", "Smells Like Teen Spirit", "Billie Jean",
                "Hey Jude", "Let It Be", "What a Wonderful World", "Thriller", "Purple Rain",
                "Respect", "My Way", "Sweet Child O' Mine", "Hallelujah", "Wonderwall",
                "Rolling in the Deep", "Shape of You", "Despacito", "Uptown Funk",
                "Old Town Road", "Blinding Lights", "Somebody That I Used to Know",
                "Happy", "Bad Guy", "Lose Yourself", "Under Pressure", "Dancing Queen"
            ],
            "sport": [
                "Soccer", "Basketball", "Tennis", "Cricket", "Baseball", "Golf", "Rugby",
                "Swimming", "Athletics", "Boxing", "Hockey", "Volleyball", "Table Tennis",
                "Badminton", "Skiing", "Cycling", "Gymnastics", "Wrestling", "Fencing",
                "Archery", "Surfing", "Skateboarding", "Rowing", "Sailing", "Judo",
                "Karate", "Taekwondo", "Handball", "Polo", "Formula One"
            ],
            "food": [
                "Pizza", "Sushi", "Hamburger", "Tacos", "Pasta", "Ramen", "Curry",
                "Paella", "Dim Sum", "Croissant", "Biryani", "Kebab", "Pho",
                "Fish and Chips", "Pad Thai", "Falafel", "Peking Duck", "Lasagna",
                "Steak", "Fried Chicken", "Hot Dog", "Burrito", "Ceviche", "Hummus",
                "Tiramisu", "Cheesecake", "Gelato", "Chocolate", "Pancakes", "Waffles"
            ],
            "dish": [
                "Pizza", "Sushi", "Hamburger", "Tacos", "Pasta", "Ramen", "Curry",
                "Paella", "Dim Sum", "Croissant", "Biryani", "Kebab", "Pho",
                "Fish and Chips", "Pad Thai", "Falafel", "Peking Duck", "Lasagna",
                "Steak", "Fried Chicken", "Hot Dog", "Burrito", "Ceviche", "Hummus",
                "Tiramisu", "Cheesecake", "Gelato", "Chocolate", "Pancakes", "Waffles"
            ],
            "brand": [
                "Apple", "Google", "Microsoft", "Amazon", "Tesla", "Nike", "Coca-Cola",
                "Samsung", "Toyota", "McDonald's", "Disney", "Netflix", "Facebook",
                "Mercedes-Benz", "BMW", "Louis Vuitton", "Gucci", "Adidas", "Pepsi",
                "Intel", "IBM", "Sony", "Honda", "Starbucks", "IKEA",
                "Ferrari", "Rolex", "Chanel", "Visa", "Oracle"
            ],
            "company": [
                "Apple", "Google", "Microsoft", "Amazon", "Tesla", "Nike", "Coca-Cola",
                "Samsung", "Toyota", "McDonald's", "Disney", "Netflix", "Meta",
                "Mercedes-Benz", "BMW", "SpaceX", "Uber", "Airbnb", "Spotify",
                "Intel", "IBM", "Sony", "Honda", "Starbucks", "IKEA",
                "Ferrari", "Alibaba", "Tencent", "Visa", "Oracle"
            ],
            "color": [
                "Red", "Blue", "Green", "Yellow", "Orange", "Purple", "Pink", "Black",
                "White", "Brown", "Gray", "Cyan", "Magenta", "Turquoise", "Violet",
                "Indigo", "Maroon", "Navy", "Teal", "Gold", "Silver", "Beige",
                "Coral", "Crimson", "Lavender", "Ivory", "Olive", "Salmon", "Scarlet", "Tan"
            ],
            "element": [
                "Gold", "Silver", "Iron", "Copper", "Carbon", "Oxygen", "Hydrogen", "Helium",
                "Lithium", "Beryllium", "Boron", "Nitrogen", "Fluorine", "Neon", "Sodium",
                "Magnesium", "Aluminum", "Silicon", "Phosphorus", "Sulfur", "Chlorine", "Argon",
                "Potassium", "Calcium", "Zinc", "Mercury", "Lead", "Tin", "Platinum", "Uranium",
                "Titanium", "Nickel", "Cobalt", "Chromium", "Manganese"
            ],
            "language": [
                "English", "Spanish", "Mandarin", "Hindi", "Arabic", "French", "Portuguese",
                "Russian", "Japanese", "German", "Korean", "Italian", "Turkish", "Dutch",
                "Polish", "Swedish", "Greek", "Hebrew", "Thai", "Vietnamese",
                "Indonesian", "Swahili", "Persian", "Czech", "Romanian", "Hungarian",
                "Finnish", "Norwegian", "Danish", "Latin"
            ],
            "instrument": [
                "Piano", "Guitar", "Violin", "Drums", "Flute", "Trumpet", "Saxophone",
                "Cello", "Clarinet", "Harp", "Trombone", "Oboe", "Banjo", "Ukulele",
                "Accordion", "Harmonica", "Organ", "Bass Guitar", "Mandolin", "Sitar",
                "Tabla", "Bagpipes", "Xylophone", "Marimba", "French Horn",
                "Tuba", "Piccolo", "Viola", "Double Bass", "Synthesizer"
            ],
            "river": [
                "Amazon", "Nile", "Mississippi", "Yangtze", "Danube", "Ganges", "Rhine",
                "Thames", "Seine", "Mekong", "Congo", "Volga", "Euphrates", "Tigris",
                "Colorado", "Niger", "Murray", "Zambezi", "Indus", "Rio Grande",
                "Hudson", "Elbe", "Po", "Oder", "Don", "Lena", "Ob", "Yenisei"
            ],
            "mountain": [
                "Mount Everest", "K2", "Kangchenjunga", "Mont Blanc", "Matterhorn",
                "Mount Kilimanjaro", "Mount Fuji", "Denali", "Mount Elbrus", "Aconcagua",
                "Mount Olympus", "Mount Rainier", "Mount Vesuvius", "Mount Etna",
                "Ben Nevis", "Table Mountain", "Mount McKinley", "Annapurna",
                "Mount Rushmore", "Mount St. Helens", "Pikes Peak", "Mount Hood"
            ],
            "ocean": [
                "Pacific Ocean", "Atlantic Ocean", "Indian Ocean", "Southern Ocean",
                "Arctic Ocean", "Mediterranean Sea", "Caribbean Sea", "South China Sea",
                "Red Sea", "Black Sea", "Baltic Sea", "North Sea", "Caspian Sea",
                "Arabian Sea", "Sea of Japan", "Coral Sea", "Bering Sea"
            ],
            "continent": [
                "Africa", "Antarctica", "Asia", "Europe", "North America",
                "Oceania", "South America", "Australia"
            ],
            "tv_show": [
                "Game of Thrones", "Breaking Bad", "Friends", "The Office", "Stranger Things",
                "The Simpsons", "Seinfeld", "The Sopranos", "The Wire", "Lost",
                "House of Cards", "Dexter", "Grey's Anatomy", "The Walking Dead",
                "Sherlock", "Doctor Who", "Black Mirror", "Narcos", "The Crown",
                "Ted Lasso", "Succession", "The Mandalorian", "Squid Game",
                "Peaky Blinders", "The Big Bang Theory", "How I Met Your Mother",
                "Parks and Recreation", "The West Wing", "Mad Men", "Downton Abbey"
            ],
            "video_game": [
                "Minecraft", "Fortnite", "Tetris", "Super Mario Bros", "The Legend of Zelda",
                "Grand Theft Auto", "Call of Duty", "Pac-Man", "Pokémon", "FIFA",
                "Sonic the Hedgehog", "Halo", "World of Warcraft", "Roblox",
                "League of Legends", "Elden Ring", "Skyrim", "Red Dead Redemption",
                "Among Us", "Overwatch", "Dark Souls", "Final Fantasy", "Resident Evil",
                "Metal Gear Solid", "Street Fighter", "Mortal Kombat", "Diablo",
                "Animal Crossing", "God of War", "Cyberpunk 2077"
            ],
            "invention": [
                "Wheel", "Printing Press", "Steam Engine", "Telephone", "Light Bulb",
                "Airplane", "Internet", "Compass", "Gunpowder", "Transistor",
                "Penicillin", "Vaccine", "Television", "Radio", "Computer",
                "Telescope", "Microscope", "Camera", "Automobile", "Bicycle",
                "Battery", "Dynamite", "Refrigerator", "Washing Machine", "X-ray"
            ],
            "currency": [
                "US Dollar", "Euro", "Japanese Yen", "British Pound", "Swiss Franc",
                "Chinese Yuan", "Australian Dollar", "Canadian Dollar", "Indian Rupee",
                "Brazilian Real", "Mexican Peso", "South Korean Won", "Russian Ruble",
                "Singapore Dollar", "Swedish Krona", "Norwegian Krone", "Turkish Lira",
                "Saudi Riyal", "Thai Baht", "South African Rand"
            ],
            "holiday": [
                "Christmas", "Easter", "Halloween", "Thanksgiving", "New Year",
                "Valentine's Day", "Independence Day", "Diwali", "Hanukkah", "Ramadan",
                "Chinese New Year", "Eid al-Fitr", "Cinco de Mayo", "Mardi Gras",
                "St. Patrick's Day", "Labor Day", "Memorial Day", "Boxing Day"
            ],
            "dessert": [
                "Ice Cream", "Chocolate Cake", "Cheesecake", "Tiramisu", "Crème Brûlée",
                "Baklava", "Macaron", "Brownie", "Cookie", "Donut",
                "Pudding", "Cupcake", "Éclair", "Panna Cotta", "Mochi",
                "Apple Pie", "Pavlova", "Cannoli", "Churros", "Profiterole"
            ],
            "flower": [
                "Rose", "Tulip", "Sunflower", "Lily", "Orchid", "Daisy", "Lotus",
                "Chrysanthemum", "Lavender", "Jasmine", "Dahlia", "Carnation",
                "Iris", "Poppy", "Hibiscus", "Magnolia", "Peony", "Marigold",
                "Daffodil", "Violet", "Cherry Blossom", "Gardenia", "Bluebell"
            ],
            "gemstone": [
                "Diamond", "Ruby", "Emerald", "Sapphire", "Amethyst", "Opal",
                "Topaz", "Pearl", "Garnet", "Aquamarine", "Turquoise", "Jade",
                "Onyx", "Tanzanite", "Peridot", "Citrine", "Moonstone", "Lapis Lazuli"
            ],
            "dance": [
                "Waltz", "Tango", "Salsa", "Ballet", "Hip Hop", "Breakdancing",
                "Samba", "Flamenco", "Cha-Cha", "Foxtrot", "Swing", "Rumba",
                "Bollywood", "Line Dance", "Contemporary", "Jazz", "Tap Dance",
                "Polka", "Bachata", "Merengue"
            ],
            "mythology": [
                "Zeus", "Thor", "Athena", "Poseidon", "Aphrodite", "Odin", "Hera",
                "Apollo", "Artemis", "Loki", "Hercules", "Perseus", "Medusa",
                "Achilles", "Hades", "Ares", "Freya", "Ra", "Anubis", "Isis",
                "Brahma", "Vishnu", "Shiva", "Amaterasu", "Quetzalcoatl"
            ],
            "landmark": [
                "Eiffel Tower", "Great Wall of China", "Taj Mahal", "Statue of Liberty",
                "Colosseum", "Machu Picchu", "Stonehenge", "Big Ben", "Pyramids of Giza",
                "Sydney Opera House", "Christ the Redeemer", "Parthenon", "Angkor Wat",
                "Leaning Tower of Pisa", "Burj Khalifa", "Golden Gate Bridge",
                "Petra", "Hagia Sophia", "Chichen Itza", "Mount Rushmore",
                "Tower of London", "Forbidden City", "Notre-Dame", "Sagrada Familia"
            ],
            "dinosaur": [
                "Tyrannosaurus Rex", "Triceratops", "Velociraptor", "Stegosaurus",
                "Brachiosaurus", "Pterodactyl", "Ankylosaurus", "Diplodocus",
                "Spinosaurus", "Allosaurus", "Parasaurolophus", "Iguanodon",
                "Pachycephalosaurus", "Apatosaurus", "Carnotaurus", "Dilophosaurus"
            ],
            "constellation": [
                "Orion", "Ursa Major", "Ursa Minor", "Cassiopeia", "Scorpius",
                "Leo", "Gemini", "Aquarius", "Sagittarius", "Taurus",
                "Virgo", "Pisces", "Aries", "Cancer", "Libra", "Capricornus",
                "Andromeda", "Pegasus", "Cygnus", "Canis Major"
            ],
            "board_game": [
                "Chess", "Monopoly", "Scrabble", "Risk", "Clue", "Checkers",
                "Backgammon", "Go", "Battleship", "Trivial Pursuit", "Stratego",
                "Settlers of Catan", "Ticket to Ride", "Pandemic", "Codenames",
                "Mahjong", "Dominoes", "Connect Four", "Life", "Sorry"
            ],
            "musical": [
                "Hamilton", "The Phantom of the Opera", "Les Misérables", "Wicked",
                "The Lion King", "Chicago", "Cats", "West Side Story", "Grease",
                "Rent", "Mamma Mia", "Annie", "Fiddler on the Roof", "Cabaret",
                "Dear Evan Hansen", "Hairspray", "Frozen", "Sweeney Todd",
                "Miss Saigon", "The Sound of Music"
            ],
            "programming_language": [
                "Python", "JavaScript", "Java", "C", "C++", "C#", "TypeScript",
                "Ruby", "Go", "Rust", "Swift", "Kotlin", "PHP", "R", "MATLAB",
                "Perl", "Scala", "Lua", "Haskell", "Dart", "Elixir", "Clojure",
                "Assembly", "COBOL", "Fortran", "SQL", "HTML", "CSS", "Shell"
            ],
            "car": [
                "Toyota Camry", "Honda Civic", "Ford Mustang", "BMW 3 Series",
                "Mercedes-Benz S-Class", "Tesla Model 3", "Chevrolet Corvette",
                "Porsche 911", "Ferrari F40", "Lamborghini Aventador",
                "Audi A4", "Volkswagen Beetle", "Jeep Wrangler", "Range Rover",
                "Bugatti Veyron", "McLaren P1", "Rolls-Royce Phantom",
                "Nissan GT-R", "Subaru WRX", "Mini Cooper"
            ],
            "scientist": [
                "Albert Einstein", "Isaac Newton", "Marie Curie", "Galileo Galilei",
                "Charles Darwin", "Nikola Tesla", "Stephen Hawking", "Louis Pasteur",
                "Thomas Edison", "Alexander Fleming", "Alan Turing", "Niels Bohr",
                "Richard Feynman", "Michael Faraday", "James Clerk Maxwell",
                "Rosalind Franklin", "Leonardo da Vinci", "Archimedes",
                "Max Planck", "Werner Heisenberg"
            ],
            "superhero": [
                "Superman", "Batman", "Spider-Man", "Wonder Woman", "Iron Man",
                "Captain America", "Thor", "Hulk", "Black Panther", "Aquaman",
                "Flash", "Green Lantern", "Wolverine", "Deadpool", "Doctor Strange",
                "Black Widow", "Hawkeye", "Ant-Man", "Captain Marvel", "Shazam"
            ],
        }


    async def get_candidates(
        self, hint: str, history: List[Dict[str, str]], force_refresh: bool = False, bypass_offline: bool = False
    ) -> List[str]:
        """Runs the layered lookup strategy to retrieve a list of candidate entities."""
        # BUG FIX 6: Use content hash (not just length) to prevent stale cache during regrowth
        import hashlib
        history_content = json.dumps(history, sort_keys=True) if history else ""
        history_hash = hashlib.md5(history_content.encode()).hexdigest()[:8]
        cache_key = f"kb_candidates_{hint}_h{history_hash}"
        
        if not force_refresh:
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.info(f"Loaded candidates for hint '{hint}' from local cache.")
                return cached_result

        candidates: List[str] = []
        
        # Layer 1: Check Local Cache/Predefined Categories
        hint_lower = hint.lower()
        
        # Exclude compound modifier phrases that cause false category matches
        excluded_phrases = [
            "brand new", "satellite dish", "element of", "dish washer",
            "stone age", "stone wall", "stepping stone", "building block",
            "game changer", "game plan", "show off", "show up",
            "hit the", "hit by", "track record", "track down",
            "star player", "star wars", "all star", "rock star",
        ]
        is_excluded = any(phrase in hint_lower for phrase in excluded_phrases)
        
        if not is_excluded and not bypass_offline:
            import re
            hint_lower_clean = hint_lower.strip()

            # Two-tier priority matching: multi-word phrases first, then single words
            # This prevents "board game" from matching "sport" (via "game") before "board_game"
            multi_word_aliases = {
                "board_game": ["board game", "card game", "tabletop game"],
                "video_game": ["video game", "computer game"],
                "tv_show": ["tv show", "television show", "tv series", "television series"],
                "programming_language": ["programming language", "coding language"],
                "musical": ["broadway musical", "broadway show"],
                "car": ["sports car", "luxury car"],
                "scientist": ["famous scientist", "nobel laureate"],
                "superhero": ["super hero"],
            }

            # Single-word aliases (lower priority, cleaned of overly generic terms)
            single_word_aliases = {
                "country": ["country", "nation", "republic", "kingdom"],
                "animal": ["animal", "mammal", "creature", "bird", "fish", "insect", "reptile", "pet", "species", "fauna", "breed"],
                "movie": ["movie", "film", "cinema", "flick"],
                "book": ["book", "novel", "literature"],
                "person": ["person", "actor", "actress", "writer", "author", "president", "leader", "celebrity", "politician", "inventor", "explorer"],
                "fruit": ["fruit", "berry"],
                "planet": ["planet"],
                "city": ["city", "capital", "metropolis"],
                "song": ["song", "single", "tune"],
                "music": ["band", "musician", "singer", "composer"],
                "sport": ["sport", "athletics"],
                "food": ["food", "cuisine", "meal", "pasta", "snack", "recipe"],
                "brand": ["brand", "trademark"],
                "company": ["company", "corporation"],
                "color": ["color", "colour"],
                "element": ["element", "periodic"],
                "language": ["language", "tongue", "dialect"],
                "instrument": ["instrument"],
                "river": ["river", "waterway"],
                "mountain": ["mountain", "peak", "summit", "volcano"],
                "ocean": ["ocean", "sea"],
                "continent": ["continent"],
                "tv_show": ["sitcom", "television"],
                "board_game": ["tabletop"],
                "video_game": ["gaming"],
                "invention": ["invention"],
                "currency": ["currency", "money"],
                "holiday": ["holiday", "festival", "celebration"],
                "dessert": ["dessert", "pastry"],
                "flower": ["flower", "bloom", "blossom"],
                "gemstone": ["gemstone", "gem", "jewel"],
                "landmark": ["landmark", "monument"],
                "dinosaur": ["dinosaur", "prehistoric"],
                "constellation": ["constellation", "zodiac"],
                "car": ["car", "automobile", "vehicle"],
                "scientist": ["scientist", "physicist", "chemist", "biologist", "mathematician"],
                "superhero": ["superhero"],
                "dance": ["dance", "dancing", "ballet"],
                "mythology": ["mythology", "myth", "god", "goddess", "deity"],
                "musical": ["musical", "broadway", "theatre", "theater"],
                "programming_language": ["programming", "coding"],
            }

            matched_cat = None

            # Tier 1: Multi-word phrase matching (highest priority)
            for category, phrases in multi_word_aliases.items():
                if any(phrase in hint_lower_clean for phrase in phrases):
                    matched_cat = category
                    break

            # Tier 2: Single-word boundary matching
            if not matched_cat:
                for category, aliases in single_word_aliases.items():
                    if any(re.search(rf"\b{re.escape(alias)}\b", hint_lower_clean) for alias in aliases):
                        matched_cat = category
                        break
            
            # Tier 3: Direct category name match from offline DB
            if not matched_cat:
                for category in self.local_offline_db.keys():
                    if re.search(rf"\b{re.escape(category)}\b", hint_lower_clean):
                        matched_cat = category
                        break
                        
            if matched_cat and matched_cat in self.local_offline_db:
                list_of_entities = self.local_offline_db[matched_cat]
                logger.info(f"Matched offline local category '{matched_cat}' for hint '{hint}'. Loading {len(list_of_entities)} entities.")
                candidates.extend(list_of_entities)

        # Layer 2: LLM Reasoning
        if not candidates:
            logger.info("Triggering Layer 2: LLM Reasoning for candidate generation...")
            try:
                formatted_history = "\n".join(
                    [f"Q: {h.get('question', '')} -> A: {h.get('answer', '')}" for h in history if isinstance(h, dict)]
                ) if history else "None"
                
                user_prompt = USER_CANDIDATE_GEN_TEMPLATE.format(
                    hint=hint,
                    history=formatted_history
                )
                
                response_text = await self.provider.generate_response(
                    SYSTEM_CANDIDATE_GENERATION, user_prompt
                )
                
                from agp.json_utils import clean_and_parse_json
                candidates = clean_and_parse_json(response_text)
                if not isinstance(candidates, list):
                    candidates = [str(candidates)]
            except Exception as e:
                logger.error(f"LLM candidate generation failed: {e}")

        # Layer 3: Return empty list if lookup and LLM reasoning fail
        if not candidates:
            logger.warning(f"All lookup layers failed for hint '{hint}'. Returning empty candidate set.")
            candidates = []

        # Clean and filter duplicates
        unique_candidates = []
        seen = set()
        for c in candidates:
            c_clean = c.strip()
            c_lower = c_clean.lower()
            if c_lower not in seen and c_clean:
                seen.add(c_lower)
                unique_candidates.append(c_clean)

        # Cache result for 1 hour
        cache.set(cache_key, unique_candidates, ttl_seconds=3600)
        return unique_candidates
