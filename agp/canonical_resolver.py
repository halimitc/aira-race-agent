import json
from typing import Dict
from logger import logger
from prompts import SYSTEM_CANONICAL_RESOLVER
from agp.reasoning_provider import ReasoningProvider

class CanonicalResolver:
    """Resolves entity names to their canonical/standard form before guessing."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider
        # Hardcoded map of common abbreviations/variants to speed up lookups
        self.lookup_table: Dict[str, str] = {
            # Countries
            "usa": "United States", "us": "United States", "u.s.": "United States",
            "u.s.a.": "United States", "united states of america": "United States",
            "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom",
            "great britain": "United Kingdom", "england": "United Kingdom",
            "united kingdom of great britain and northern ireland": "United Kingdom",
            "uae": "United Arab Emirates", "ussr": "Soviet Union", "soviet union": "Soviet Union",
            "prc": "China", "peoples republic of china": "China", "people's republic of china": "China",
            "eu": "European Union", "un": "United Nations",
            "south korea": "South Korea", "north korea": "North Korea",
            "drc": "Democratic Republic of the Congo", "rok": "South Korea", "dprk": "North Korea",
            "czech republic": "Czechia", "holland": "Netherlands",
            "ivory coast": "Côte d'Ivoire", "burma": "Myanmar",
            # Cities
            "nyc": "New York", "la": "Los Angeles", "sf": "San Francisco",
            "dc": "Washington, D.C.", "hk": "Hong Kong",
            # Famous people
            "mlk": "Martin Luther King Jr.", "jfk": "John F. Kennedy",
            "fdr": "Franklin D. Roosevelt", "abe lincoln": "Abraham Lincoln",
            "da vinci": "Leonardo da Vinci", "einstein": "Albert Einstein",
            "newton": "Isaac Newton", "shakespeare": "William Shakespeare",
            "beethoven": "Ludwig van Beethoven", "mozart": "Wolfgang Amadeus Mozart",
            "gandhi": "Mahatma Gandhi", "mandela": "Nelson Mandela",
            "cleopatra": "Cleopatra VII", "napoleon": "Napoleon Bonaparte",
            # Tech/Brands
            "fb": "Facebook", "meta": "Meta", "ms": "Microsoft", "amzn": "Amazon",
            "tsla": "Tesla", "goog": "Google", "aapl": "Apple", "ibm": "IBM",
            # Common abbreviations
            "t-rex": "Tyrannosaurus Rex", "t. rex": "Tyrannosaurus Rex",
            "mt. everest": "Mount Everest", "mt everest": "Mount Everest",
            "mt. fuji": "Mount Fuji", "mt fuji": "Mount Fuji",
            "mt. kilimanjaro": "Mount Kilimanjaro",
            "statue of liberty": "Statue of Liberty",
            "great wall": "Great Wall of China",
            # Elements
            "h2o": "Water", "co2": "Carbon Dioxide", "o2": "Oxygen", "n2": "Nitrogen",
        }

    async def resolve(self, entity: str) -> str:
        """Resolves an entity to its canonical name using lookup table or LLM reasoning."""
        cleaned_entity = entity.strip().lower()
        
        # Direct lookup
        if cleaned_entity in self.lookup_table:
            resolved = self.lookup_table[cleaned_entity]
            logger.info(f"Resolved canonical entity: '{entity}' -> '{resolved}' (Local Table)")
            return resolved

        # FAST BYPASS: If entity is clean text (e.g. "Albert Einstein", "Eiffel Tower", "Piano") without abbreviations/dots
        if not any(char in cleaned_entity for char in [".", "/", "\\", "(", ")"]) and len(cleaned_entity) > 2:
            self.lookup_table[cleaned_entity] = entity.strip()
            return entity.strip()

        # Fallback to LLM reasoning
        logger.info(f"Resolving canonical name for '{entity}' via LLM...")
        try:
            user_prompt = f"Resolve this entity name to its canonical form: '{entity}'"
            response_text = await self.provider.generate_response(
                SYSTEM_CANONICAL_RESOLVER, user_prompt
            )
            
            from agp.json_utils import clean_and_parse_json
            data = clean_and_parse_json(response_text)
            if isinstance(data, dict):
                canonical_name = str(data.get("canonical_name") or entity).strip()
            elif isinstance(data, str):
                canonical_name = data.strip()
            else:
                canonical_name = entity
            
            # Cache resolved result in lookup table
            self.lookup_table[cleaned_entity] = canonical_name
            logger.info(f"Resolved canonical entity: '{entity}' -> '{canonical_name}' (LLM Resolver)")
            return canonical_name
            
        except Exception as e:
            logger.warning(f"Canonical resolver failed for '{entity}': {e}. Returning original.")
            return entity

    async def resolve_batch(self, entities: list[str]) -> dict[str, str]:
        """Resolves a batch of entity names into a mapping dictionary {original: canonical} in parallel."""
        import asyncio
        tasks = [self.resolve(entity) for entity in entities]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        mapping = {}
        for entity, res in zip(entities, results):
            if isinstance(res, str) and res:
                mapping[entity] = res
            else:
                mapping[entity] = entity
        return mapping

