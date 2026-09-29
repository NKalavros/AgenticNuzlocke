"""Gen 1 evolution families; acquisition history survives deaths and evolution."""

_GROUPS = """
Bulbasaur Ivysaur Venusaur
Charmander Charmeleon Charizard
Squirtle Wartortle Blastoise
Caterpie Metapod Butterfree
Weedle Kakuna Beedrill
Pidgey Pidgeotto Pidgeot
Rattata Raticate
Spearow Fearow
Ekans Arbok
Pikachu Raichu
Sandshrew Sandslash
NidoranF Nidorina Nidoqueen
NidoranM Nidorino Nidoking
Clefairy Clefable
Vulpix Ninetales
Jigglypuff Wigglytuff
Zubat Golbat
Oddish Gloom Vileplume
Paras Parasect
Venonat Venomoth
Diglett Dugtrio
Meowth Persian
Psyduck Golduck
Mankey Primeape
Growlithe Arcanine
Poliwag Poliwhirl Poliwrath
Abra Kadabra Alakazam
Machop Machoke Machamp
Bellsprout Weepinbell Victreebel
Tentacool Tentacruel
Geodude Graveler Golem
Ponyta Rapidash
Slowpoke Slowbro
Magnemite Magneton
Doduo Dodrio
Seel Dewgong
Grimer Muk
Shellder Cloyster
Gastly Haunter Gengar
Drowzee Hypno
Krabby Kingler
Voltorb Electrode
Exeggcute Exeggutor
Cubone Marowak
Koffing Weezing
Rhyhorn Rhydon
Horsea Seadra
Goldeen Seaking
Staryu Starmie
Magikarp Gyarados
Eevee Vaporeon Jolteon Flareon
Omanyte Omastar
Kabuto Kabutops
Dratini Dragonair Dragonite
"""


def canonical(name: str) -> str:
    return "".join(c for c in name.upper().replace("♀", "F").replace("♂", "M") if c.isalnum())


_FAMILIES = {
    canonical(n): canonical(line.split()[0]) for line in _GROUPS.splitlines() for n in line.split()
}


def family(name: str) -> str:
    key = canonical(name)
    return _FAMILIES.get(key, key)
