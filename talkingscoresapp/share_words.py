"""The words an uploaded score's share link is made from: one from each list.

Every word is read as a whole word by screen readers and text-to-speech, sounds
like no other common English word, and appears in one list only. "piano" is left
out: it names both an instrument and a dynamic. Adding or removing a word changes
no existing link, since each link is stored once it is made.
"""

TEMPOS_AND_MOODS = (
    "adagio", "agile", "airy", "allegretto", "allegro", "amber", "andante", "andantino", "animato", "arioso",
    "autumn", "balmy", "bold", "brave", "breezy", "bright", "brilliant", "brisk", "buoyant", "calm",
    "candid", "cantabile", "cheerful", "sparkling", "clever", "cosy", "crisp", "dancing", "dapper", "dolce",
    "dreamy", "eager", "early", "earnest", "easy", "fervent", "festive", "fleet", "fluent", "frosty",
    "gentle", "giocoso", "glad", "gleaming", "glowing", "golden", "graceful", "grand", "grazioso", "happy",
    "hearty", "hopeful", "humble", "jolly", "jovial", "joyful", "kindly", "largo", "legato", "lento",
    "lilting", "limpid", "lively", "lofty", "lucid", "lunar", "lyrical", "maestoso", "marcato", "mellow",
    "merry", "misty", "moderato", "nimble", "noble", "pensive", "placid", "playful", "presto", "proud",
    "quiet", "radiant", "rustic", "serene", "silver", "solemn", "spirited", "sprightly", "stately", "steady",
    "sunny", "swift", "tender", "tranquil", "velvet", "vivace", "vivid", "warm", "wistful", "zesty",
)

INSTRUMENTS = (
    "accordion", "bagpipe", "balalaika", "banjo", "bassoon", "bongo", "bouzouki", "bugle", "cajon", "carillon",
    "castanet", "celesta", "cello", "chimes", "cittern", "clarinet", "clavichord", "concertina", "conga", "cornet",
    "crumhorn", "didgeridoo", "djembe", "drum", "dulcimer", "erhu", "euphonium", "fiddle", "flugelhorn", "flute",
    "glockenspiel", "gong", "guitar", "guzheng", "handbell", "harmonica", "harmonium", "harp", "harpsichord", "horn",
    "hurdygurdy", "kalimba", "kazoo", "kettledrum", "koto", "mandola", "mandolin", "maracas", "marimba", "melodica",
    "mellophone", "ocarina", "organ", "oud", "panpipe", "piccolo", "pipa", "psaltery", "rebec", "recorder",
    "sackbut", "santoor", "sarangi", "saxophone", "shakuhachi", "shamisen", "shawm", "sitar", "snare", "sousaphone",
    "spinet", "tabla", "tabor", "tambourine", "theorbo", "timpani", "kantele", "triangle", "trombone", "trumpet",
    "tuba", "ukulele", "vibraphone", "vielle", "viola", "violin", "virginal", "washboard", "whistle", "woodblock",
    "xylophone", "zither", "zurna", "bandoneon", "baritone", "bodhran", "charango", "steelpan", "fife", "gamelan",
)

FORMS = (
    "allemande", "anthem", "aria", "arietta", "bagatelle", "ballad", "barcarolle", "berceuse", "bolero", "boogie",
    "bourree", "cakewalk", "canon", "cantata", "canzona", "capriccio", "carol", "cavatina", "chaconne", "chant",
    "chorale", "concerto", "courante", "czardas", "divertimento", "duet", "ecossaise", "elegy", "etude", "fandango",
    "fanfare", "fantasia", "farandole", "fugue", "galop", "gavotte", "gigue", "habanera", "hornpipe", "humoresque",
    "impromptu", "intermezzo", "invention", "jig", "lament", "lullaby", "madrigal", "mambo", "march", "mazurka",
    "minuet", "motet", "musette", "nocturne", "octet", "opera", "operetta", "oratorio", "overture", "partita",
    "passacaglia", "pastorale", "pavane", "polka", "polonaise", "prelude", "quadrille", "quartet", "quintet", "ragtime",
    "rigaudon", "requiem", "rhapsody", "ricercar", "romance", "rondo", "round", "rumba", "samba", "sarabande",
    "scherzo", "serenade", "sextet", "shanty", "siciliano", "sinfonia", "sonata", "sonatina", "symphony", "tango",
    "tarantella", "toccata", "trio", "variations", "villanelle", "waltz", "estampie", "forlana", "jota", "nonet",
)
