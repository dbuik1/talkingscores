"""The 20 scores in our own test set, all from the corpus bundled with music21.

Each entry becomes one page: the opening bars of the score, as many as fit on
one A4 page. The mix follows what readers bring: piano music, songs with
lyrics, choirs, string quartets, small ensembles and single-line tunes.
"""

PIECES = [
    # id, music21 corpus path, texture, title printed on the page
    ("bach-prelude-c", "bach/bwv846.mxl", "piano", "Prelude in C major"),
    ("mozart-k545", "mozart/k545/movement1_exposition.mxl", "piano", "Sonata in C major"),
    ("joplin-maple-leaf", "joplin/maple_leaf_rag.mxl", "piano", "Maple Leaf Rag"),
    ("chopin-mazurka", "chopin/mazurka06-2.krn", "piano", "Mazurka in C sharp minor"),
    ("clara-polonaise", "schumann_clara/polonaise_op1n1.mxl", "piano", "Polonaise"),
    ("verdi-donna", "verdi/laDonnaEMobile.mxl", "piano", "La donna è mobile"),
    ("schubert-lindenbaum", "schubert/Lindenbaum.xml", "voice and piano", "Der Lindenbaum"),
    ("schumann-dichterliebe", "schumann_robert/dichterliebe_no2.xml", "voice and piano", "Aus meinen Tränen spriessen"),
    ("handel-lascia", "handel/rinaldo/Lascia_chio_pianga.mxl", "voice and piano", "Lascia ch'io pianga"),
    ("bach-chorale-66", "bach/bwv66.6.mxl", "choir", "Chorale"),
    ("beethoven-op18-1", "beethoven/opus18no1/movement1.mxl", "quartet", "String Quartet in F major"),
    ("haydn-op74-1", "haydn/opus74no1/movement1.mxl", "quartet", "String Quartet in C major"),
    ("mozart-k458", "mozart/k458/movement1.mxl", "quartet", "String Quartet in B flat major"),
    ("corelli-op3-1", "corelli/opus3no1/1grave.xml", "ensemble", "Trio Sonata"),
    ("webern-dormi", "webern/webern_dormi_jesu_op_16_no_2.mxl", "ensemble", "Dormi Jesu"),
    ("weber-concertino", "weber/concertino_clarinet.mxl", "ensemble", "Concertino"),
    ("foster-brown-hair", "leadSheet/fosterBrownHair.mxl", "single line", "Jeanie with the Light Brown Hair"),
    ("berlin-ragtime", "leadSheet/berlinAlexandersRagtime.mxl", "single line", "Alexander's Ragtime Band"),
    ("essen-folksong", "essenFolksong/altdeu10.abc", "single line", "Folk song"),
    ("oneill-valley", "oneills1850/0001-0050.abc", "single line", "The Enchanted Valley"),
]
