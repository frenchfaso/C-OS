# C-Script: linguaggio userspace di C-OS

Specifica 0.1, revisione 4 — 10 ottobre 2026. Allegato normativo a [SPEC.md](SPEC.md). Nome di progetto: **C-Script**; estensione sorgente `.cos`.

L'obiettivo è la semplicità di un piccolo BASIC, con funzioni, variabili locali, blocchi e sintassi familiare a chi conosce JavaScript o Lua. C-Script viene compilato sul computer di sviluppo direttamente nel bytecode C-OS. Sul C64 gira soltanto la VM assembly: niente parser, interprete del linguaggio, JIT o runtime dinamico aggiuntivo.

## 1 Perimetro della prima versione

Inclusi: variabili con inferenza locale, interi 8/16/32 bit, float24 e float32, booleani, funzioni, condizioni, cicli, array di byte lineari, viste su testo/buffer e moduli SDK. Il compilatore è parte dell'MVP, anche se viene dopo i test fondamentali della VM. [NUMERICS.md](NUMERICS.md) definisce formati, arrotondamento, conversioni, backend e test numerici.

Esclusi: oggetti dinamici, classi, metatable, closure, coroutine del linguaggio, eccezioni, eval, generics, float16, double, garbage collection, caricamento dinamico di moduli e compilazione sul dispositivo. Non promettere compatibilità sorgente con JS, Lua, Python o Ruby.

Un ciclo senza yield resta preemptibile. Il compilatore non deve inserire punti di cooperazione come unica difesa contro il monopolio della CPU: il dispatcher VM consuma fuel per ogni opcode eseguito, anche dentro le librerie generate.

## 2 Aspetto del linguaggio

```text
import ui
import system
import text

fn main() {
    let win, err = ui.open("Contatore", 240, 152)
    if err != 0 { return }

    let count: long = 0
    let buffer = bytes(12)

    while true {
        let event, wait_error = ui.wait(win, 1)
        if wait_error == 0 && event.kind == ui.CLOSE_REQUEST {
            break
        }

        count = count + 1
        ui.fill(win, 8, 8, 120, 8, ui.WHITE)
        ui.text(win, 8, 8, text.decimal(buffer, count), ui.BLACK, ui.WHITE)
        ui.present(win)
    }

    ui.close(win)
}
```

Il sorgente è un esempio normativo per sintassi e binding da realizzare; non è codice già compilato. Ogni passaggio del ciclo ridisegna un'area piccola. `ui.wait` e `ui.present` possono sospendere questo processo senza sospendere gli altri. Il buffer viene allocato una sola volta.

## 3 Lessico e blocchi

- File UTF-8; identificatori ASCII, case sensitive: lettere, cifre e underscore, senza cifra iniziale.
- Commenti `//` fino a fine riga. Nessuna necessità di commenti annidati.
- Blocchi fra `{` e `}`; niente indentazione significativa.
- Un newline termina una semplice istruzione, salvo dentro `()`/`[]` o dopo un operatore che richiede un operando. Il punto e virgola è un separatore esplicito alternativo.
- Interi decimali e `0x` esadecimali; underscore solo fra cifre. Letterali frazionari come `0.5`, `1.0`, `1e-3`, massimo 128 byte per token; quando il punto è presente richiede cifre su entrambi i lati. `1..10` resta un intervallo intero.
- Stringhe fra doppi apici; escape `\n`, `\r`, `\t`, `\"`, `\\`, `\xNN`.
- I byte di testo fuori ASCII devono essere scritti con escape espliciti nella versione 0.1. La UI visualizza solo i glifi previsti dalla specifica principale.
- Parole riservate: `import`, `fn`, `let`, `const`, `if`, `else`, `while`, `for`, `in`, `break`, `continue`, `return`, `true`, `false` e i nomi dei tipi primitivi.

Le chiamate sono espressioni. Una chiamata usata come istruzione può ignorare i risultati; il compilatore segnala un warning per risultati d'errore ignorati dei servizi I/O. Nei sorgenti di accettazione, tutti gli errori che possono perdere dati devono essere gestiti.

## 4 Tipi e rappresentazione

| Tipo | Rappresentazione | Impiego |
|---|---|---|
| `bool` | Un byte, solo 0/1 | Condizioni |
| `byte` | u8 | Pixel, dati, registri SID |
| `word` | u16 | Conteggi piccoli, flag, codici d'errore |
| `int` | i16 | Intero normale, coordinate |
| `dword` | u32 | Dimensioni, indici grandi, posizioni file |
| `long` | i32 | Calcoli interi più grandi |
| `float24` | 3 byte, 16 bit significativi | Calcoli e dati frazionari compatti, circa 4–5 cifre |
| `float32`, `float` | 4 byte, 24 bit significativi | Calcoli frazionari con circa 6–7 cifre; float è un alias |
| `bytes` | Puntatore u24 + lunghezza u32, 7 byte | Vista modificabile di byte |
| `str` | Puntatore u24 + lunghezza u32, 7 byte | Vista di testo in sola lettura |
| `Window`, `File`, `Dir`, `SID`, `PCM` | Handle u16, tipi distinti | Risorse del kernel |
| Record SDK | Campi fissi e layout dichiarato | InputState 8 byte; Event/DateTime/StorageInfo 16 byte; FileInfo 32 byte |

Tutti i campi multibyte in memoria guest sono little endian e packed; nessun padding implicito. L'ABI hardware dei driver può essere diverso ed è responsabilità del kernel convertirlo.

I record SDK sono valori con campi leggibili, anche annidati, per esempio `info.modified.year`; non si modificano passando puntatori ai campi interni. Risultati multipli come `(FileInfo, bool, word)` stanno nel blocco risultati statico del chiamante e non richiedono allocazioni heap. Il nome di una voce directory viene scritto in un buffer fornito dall'app e non è un puntatore temporaneo dentro FileInfo.

In Event, `arg0` e `arg1` hanno tipo `int`: le coordinate client negative sono leggibili direttamente, senza cast da word. `arg2` resta word. InputState e il binding `ui.input_state` sono definiti nell'SDK; il record permette di rileggere lo stato dopo INPUT_RESET senza introdurre handle o allocazioni.

Gli handle non si sommano e non si convertono in puntatori. Il valore zero indica un handle invalido negli output d'errore. I tipi opachi non possono essere costruiti da un intero nel linguaggio; la VM controlla comunque proprietario e validità per il bytecode scritto a mano.

Il linguaggio non espone puntatori nativi, indirizzi dei registri o `peek/poke`. Le viste su buffer usano i puntatori lineari a 24 bit della VM. Lunghezze e indici a 32 bit impediscono di troncare un buffer a 64 KiB.

### 4.1 Inferenza e conversioni

`let x = 12` crea un `int` modificabile. `let x: word = 12` dà un tipo esplicito. `const` richiede un'espressione valutabile a compilazione e non consente riassegnazione. Il tipo di una variabile non cambia dopo l'inizializzazione; niente variabili non inizializzate.

L'inferenza procede dal basso verso l'alto nell'albero delle espressioni. È un **letterale diretto** un token numerico, anche racchiuso soltanto da parentesi e meno unario; il valore esatto include il segno prima del controllo del range. Nomi di costanti, cast e sottoespressioni con operatori binari sono già tipizzati e non sono letterali diretti. Un contesto esterno non modifica i tipi delle loro parti.

Una dichiarazione, assegnazione, parametro o risultato atteso può dare il tipo a un letterale diretto; lo stesso vale per un cast applicato direttamente al letterale. Un letterale intero richiesto come intero deve essere rappresentabile. Senza contesto è `int` se possibile, altrimenti `long`, altrimenti `dword`; un valore che non entra in questi tipi è errore. Questo include correttamente −32.768 e −2.147.483.648 e rifiuta i negativi inferiori al minimo long. I letterali frazionari senza contesto sono float32; un contesto float24 li arrotonda direttamente a quel formato secondo NUMERICS.md §3. Un letterale frazionario non assume implicitamente un tipo intero.

Per un operatore binario, tipizzare prima gli operandi che non sono letterali diretti. Se uno solo è un letterale diretto e l'altro è un numero tipizzato, provare il tipo dell'altro: un intero lo adotta se rappresentabile; un formato float accetta il letterale numerico con il proprio arrotondamento. Altrimenti il letterale prende il tipo senza contesto e si cercano le conversioni ordinarie. Se entrambi sono letterali diretti, entrambi prendono il tipo senza contesto. Questa regola vale anche per gli estremi del for; gli shift seguono la regola separata sotto. Il tipo atteso all'esterno dell'operatore non viene propagato ai suoi operandi.

Conversioni implicite solo quando preservano tutti i valori: byte→word/dword/int/long, word→dword/long, int→long; inoltre byte/word/int→float24/float32 e float24→float32. Il tipo comune di due interi è il tipo intero con intervallo minimo che contiene tutti i valori di entrambi i tipi. Se non esiste, l'operazione richiede un cast esplicito; non scegliere un float come ripiego. La regola è unica per i cinque tipi interi: byte+byte produce byte, byte+int produce int, byte+word produce word, int+word produce long, word+dword produce dword; int+dword e long+dword sono errori. Long/dword→float e float32→float24 richiedono un cast.

I cast `byte(x)`, `word(x)`, `int(x)`, `dword(x)`, `long(x)` sono controllati: costante fuori range = errore di compilazione; valore runtime fuori range = fault `RANGE`. Se applicato a un letterale frazionario diretto, un cast intero tipizza prima il letterale come float32, poi applica la conversione; non interpreta il decimale come un intero né salta l'arrotondamento float32. Per conservare solo i bit bassi, mascherare esplicitamente prima del cast. Gli handle e le viste non ammettono questi cast.

Da float a integer troncare verso zero, poi verificare il range; `int(-3.75)` vale −3. I cast `float24(x)`, `float32(x)` e `float(x)` applicano RNE al formato destinazione. Non riassegnano il tipo degli operandi di un'espressione già tipizzata. Regole complete, inclusi overflow e underflow, in NUMERICS.md.

Un contesto float non trasforma un'espressione di soli interi: `float24(1 / 2)` e `let x: float24 = 1 / 2` valgono zero. Può invece fissare il formato di un letterale diretto, come `let x: float24 = (-0.5)` o `let x: float24 = 2`. Le altre conseguenze sono normative:

| Espressione, con `a24: float24` | Tipo e comportamento |
|---|---|
| `let x: float24 = 1.0 + 2.0` | Errore: la somma è float32 e richiede un cast di restringimento |
| `float24(1.0 + 2.0)` | Somma float32, poi conversione RNE a float24 |
| `a24 + (1.0 + 2.0)` | Somma interna float32; risultato esterno float32 |
| `a24 + 1.0` | Il letterale diretto assume float24; somma float24 |
| `float24(1.0) + 2.0` | Primo operando già float24; somma float24 |

### 4.2 Operatori

Ordine di precedenza, dal più debole: `||`, `&&`, `|`, `^`, `&`, `== !=`, `< <= > >=`, `<< >>`, `+ -`, `* / %`, unari `! ~ -`, chiamata/indice/campo. Gli operatori binari sono associativi a sinistra; l'assegnazione è un'istruzione, non un'espressione. Non includere `++`, `--` o assegnamenti composti nell'MVP.

`&&` e `||` valutano da sinistra e interrompono la valutazione appena il risultato è noto. Le condizioni richiedono `bool`; usare `x != 0`, non conversioni implicite di stringhe o handle in truthy/falsy.

Gli operandi di tutte le espressioni vengono valutati da sinistra a destra, salvo la valutazione abbreviata appena descritta. Per un'assegnazione a indice, valutare vista e indice, verificare i bounds, quindi valutare il valore da scrivere; ogni espressione viene valutata una sola volta.

| Operatori | Tipi ammessi e risultato |
|---|---|
| `+ - * /`, meno unario | Interi o float; operazioni binarie nel tipo comune, unarie nel tipo dell'operando |
| `%`, `&`, `|`, `^`, `~` | Soltanto interi; tipo comune per i binari, tipo dell'operando per `~` |
| `<< >>` | Operando sinistro intero; conteggio intero indipendente; risultato del tipo sinistro |
| `< <= > >=` | Soltanto numeri convertibili a un tipo comune; risultato bool |
| `== !=` | Numeri con tipo comune, due bool, oppure due handle dello stesso tipo nominale; risultato bool |
| `!`, `&&`, `||` | Soltanto bool; risultato bool |

Viste str/bytes e record non hanno uguaglianza implicita né operatori aritmetici. Per gli handle non sono ammessi confronti d'ordine o con interi. Nei confronti numerici il tipo comune riguarda gli operandi, mentre il risultato è sempre bool. Gli shift non promuovono il lato sinistro al tipo del conteggio; controllare il conteggio nel suo tipo prima di restringerlo.

Aritmetica intera a larghezza fissa, wrap modulo 2^N per somma, sottrazione, prodotto e negazione. La divisione signed tronca verso zero; il resto ha il segno del dividendo. Divisione per zero genera fault; MIN / -1 restituisce MIN per coerenza col wrap. Shift ammessi solo con conteggio 0…N−1; altrimenti fault. `>>` è aritmetico sui signed, logico sugli unsigned.

Il compilatore abbassa prodotti/divisioni e operazioni a 32 bit in sequenze VM o piccole routine bytecode. Queste routine sono soggette a fuel; nessuna moltiplicazione software deve diventare un lavoro nativo di durata illimitata. Il caso a 16 bit usa direttamente R quando possibile.

Questa regola riguarda gli interi. L'aritmetica float usa NUM_OP, il servizio nativo limitato descritto in NUMERICS.md. Float24 e float32 supportano `+ - * /`, negazione e confronti booleani; `%`, bitwise e shift restano interi. `1 / 2` vale zero, `1.0 / 2.0` vale 0,5. Le operazioni miste fra i due float producono float32; ogni operazione arrotonda al proprio tipo risultato. Un letterale senza tipo fissato adiacente a un operando float24 adotta float24, evitando promozioni involontarie.

I controlli di dimensione, allocazione, bounds e indirizzo usano aritmetica larga con rilevamento dell'overflow: **non** ereditano il wrap dell'aritmetica numerica dell'app.

## 5 Variabili e controllo del flusso

Scope lessicale per blocco, senza variabili globali modificabili nella 0.1. Costanti globali consentite. Una dichiarazione duplicata nello stesso scope è errore; segnalare lo shadowing per evitare errori semplici.

```text
const LIMIT = 100

fn sum_to(limit: int) -> int {
    let result = 0
    for i in 0..limit {
        result = result + i
    }
    return result
}
```

`for name in start..end` esclude `end`, valuta gli estremi una volta e avanza di uno. La variabile di iterazione è locale e non assegnabile nel corpo. Estremi dello stesso tipo intero dopo conversione; `end <= start` dà zero iterazioni. Il controllo di fine ciclo precede un incremento che potrebbe traboccare. Per passi diversi si usa `while`.

`break` e `continue` riguardano il ciclo più interno. `if/else if/else` e `while` richiedono blocchi. Nessun `goto` nel linguaggio sorgente.

## 6 Funzioni e risultati

Parametri sempre tipizzati; risultato omesso significa nessun risultato. Esempi: `fn twice(x: int) -> int`, `fn divide(a: int, b: int) -> (int, word)`.

Il numero e i tipi dei risultati sono statici. `return a, b` e `let value, err = call()` non creano un oggetto tuple sull'heap. Usare `_` per ignorare esplicitamente un risultato. Un valore singolo non può ricevere implicitamente il primo elemento di un risultato multiplo.

Argomenti valutati da sinistra a destra prima della chiamata. Passaggio per valore; passare una vista copia i suoi sette byte, non il buffer. I risultati devono essere definiti su ogni percorso di una funzione che restituisce valori. Le chiamate in avanti sono risolte a compilazione.

Ricorsione e chiamate annidate ammesse con firme esplicite e stack limitato dell'app; overflow di stack = fault del processo. Nessuna ricorsione implicita nel kernel e nessuna promessa di tail-call optimization. Ogni app ha un solo `fn main()` senza argomenti/risultati nel modulo entry dichiarato al compilatore; il suo ritorno termina il processo con codice zero. I moduli libreria importati non dichiarano main e non introducono altre entry.

### 6.1 ABI di chiamata C-Script

È una convenzione del compilatore sopra CALL/RET della VM, distinta dalle syscall:

1. Il chiamante prepara argomenti packed e spazio per risultati nel proprio frame sullo stack guest.
2. P0 punta al blocco argomenti, P1 al blocco risultati; zero se il rispettivo blocco è vuoto. P2 conserva il frame pointer del chiamante.
3. CALL salva il PC di ritorno secondo l'ISA. Il prologo salva il vecchio P2 con PUSHP, riserva un frame di dimensione statica con controllo dei limiti e imposta P2 al suo primo byte.
4. I puntatori ai blocchi di argomenti/risultati sono salvati nel frame prima di riusare P0/P1. I frame del chiamante restano vivi per tutta la chiamata.
5. Il callee scrive i risultati nel blocco predisposto. L'epilogo libera il proprio frame, ripristina P2 e usa RET. SP torna esattamente al valore precedente la CALL.

R0–R7, P0/P1/P3 sono caller-saved. P2 è preservato dalla convenzione C-Script, non da CALL stesso. I live value vanno salvati nei frame; non contarli come registri preservati per caso dal callee.

Limiti iniziali di compilazione: frame ≤4.096 byte, blocco argomenti ≤255 byte, risultati ≤64 byte. Record grandi e array si passano mediante viste. Il compilatore produce la dimensione di ogni frame; il manifest assegna uno stack separato, inizialmente 16 KiB per app, da includere nel budget dell'arena.

Le syscall preservano i registri secondo SPEC.md; i wrapper SDK traducono risultati e stato nel contratto del linguaggio. Ogni wrapper preserva P2 secondo l'ABI C-Script anche quando una syscall, come MEM_INFO, lo usa per un output: salva il frame pointer prima dell'invocazione, copia gli output e lo ripristina prima del ritorno. Gli helper bytecode seguono l'ABI C-Script, senza ingressi assembly app-specifici.

Il compilatore genera `_cos_start`: conserva i limiti iniziali in dati runtime privati dell'app, inizializza l'allocatore, prepara P0/P1/P2 per una chiamata senza argomenti, chiama `main` e infine PROC_EXIT(0). Non chiamare direttamente `main` con la convenzione d'ingresso del kernel, che ha significati diversi per P0…P3. I dati runtime non introducono variabili globali modificabili nel linguaggio sorgente.

## 7 Buffer lineari e memoria

```text
fn main() {
    let data = bytes(200000)
    data[70000] = 42
    data[199999] = data[70000]

    for i in 0..data.len {
        data[i] = byte(i & 15)
    }
}
```

Questo programma deve funzionare senza banco e con indici oltre 65.535. `.len` è sempre `dword`, anche quando il buffer è piccolo. L'indicizzazione accetta interi non negativi; prima della somma al puntatore controlla `index < len`. Gli indici signed negativi sono fault `BOUNDS`.

`bytes(n)` usa il bump allocator dell'app e restituisce un buffer azzerato. L'azzeramento viene effettuato tramite MEM_FILL a pezzi limitati. Niente differenza osservabile fra build diagnostica e normale; l'heap grezzo non inizializzato resta un dettaglio della VM. Lunghezza zero è ammessa; non deve causare alcun accesso REU.

Allocazione fuori heap o overflow = fault `OUT_OF_MEMORY`. Nessuna crescita automatica dell'arena. Non c'è `free`: allocare i buffer di lavoro all'avvio e riusarli. Il compilatore segnala le allocazioni dentro cicli come possibile problema, senza vietarle. Il monitor mostra high-water mark dell'heap.

L'allocatore conserva anche i byte residui a 32 bit. Quando consuma l'ultimo byte a $FFFFFF, marca l'heap esaurito senza dover rappresentare $1000000 in un puntatore. Il caso vuoto può usare la vista canonica `{ptr=0, len=0}`; nessuna sua operazione dereferenzia zero.

`data.slice(start, length)` crea una vista, senza copiare o allocare. Controlla con aritmetica larga `start <= data.len` e `length <= data.len - start`; una slice vuota non richiede di rappresentare il puntatore un byte oltre $FFFFFF. Non esporre un'operazione che trasformi la vista in un intero/puntatore arbitrario.

I buffer sono byte array nella 0.1. Array generici e strutture definite dall'utente possono arrivare dopo; i record fissi dell'SDK sono sufficienti per gli eventi. Non introdurre contenitori dinamici per ogni accesso al file o al video.

## 8 Testo

`str` è una vista read-only, non un oggetto con reference counting. Le stringhe letterali vivono nei dati statici dell'app. La 0.1 non include un operatore di concatenazione, neppure per stringhe costanti; il testo si compone esplicitamente in un buffer riusabile mediante text.copy e slice, poi si espone con text.view.

`text.view(buffer, length)` produce una vista sui primi byte del buffer, verificando i bounds; se il buffer cambia, cambia il testo osservato dalla vista. La sua durata non supera quella del processo. Non deve restituire riferimenti a temporanei dello stack.

Una str espone `.len: dword`, lettura `value[index] -> byte` e `value.slice(start, length) -> str`. Indici, bounds, aritmetica larga e slice vuote seguono le stesse regole di bytes; gli indici signed negativi causano BOUNDS. Nessuna di queste operazioni alloca o richiede nuove syscall. L'assegnazione a un indice str è un errore di compilazione, anche quando la vista è stata creata da un buffer modificabile.

Helper minimi:

| Funzione | Contratto |
|---|---|
| `text.view(src: bytes, length: dword) -> str` | Vista controllata, nessuna copia |
| `text.decimal(dst: bytes, value: long) -> str` | Decimale signed, dst ≥12 byte; BOUNDS prima di scrivere se insufficiente |
| `text.decimal(dst: bytes, value: dword) -> str` | Decimale unsigned completo 0…4.294.967.295, dst ≥12 byte; stesso controllo BOUNDS |
| `text.copy(dst: bytes, src: str) -> dword` | Copia tutti i byte, bounds fault se non entrano; lunghezza restituita |
| `text.real(dst: bytes, value: float24/float32, digits: byte) -> (str, word)` | 1…9 cifre significative; dst ≥24 byte; sovraccarico statico, nessuna allocazione |
| `text.parse_float(src: str) -> (float32, word)` | Conversione controllata da ASCII, massimo 63 byte |
| `text.parse_float24(src: str) -> (float24, word)` | Conversione diretta al formato compatto |

I due sovraccarichi text.decimal si risolvono a compilazione: byte/word/dword usano quello unsigned, int/long quello signed; un letterale diretto senza altro tipo viene prima tipizzato con le regole ordinarie. Nessuna conversione intera→float per formattare interi. Non allocano, non scrivono un NUL e restituiscono una vista dei soli byte prodotti; zero è `0`, nessun segno `+` o zero iniziale. La verifica della capacità precede ogni modifica a dst.

Le stringhe sono length-delimited, non NUL-terminated. Il driver file valida e converte i path nel formato del firmware. I testi UI devono rispettare la lunghezza massima del servizio; la libreria può dividerli in segmenti solo rispettando clipping e coordinate. La 0.1 non promette impaginazione o Unicode completo.

La grammatica, gli errori, la scelta fra forma fissa/scientifica e il round-trip numerico sono definiti in NUMERICS.md §4. I convertitori testuali sono libreria bytecode soggetta al fuel; il loro workspace deve comparire nel report dei frame.

## 9 Moduli e SDK

`import` abilita un modulo risolto dal compilatore e dal manifest di build; non carica file durante l'esecuzione. Moduli standard MVP: `system`, `ui`, `video`, `fs`, `storage`, `clock`, `sid`, `audio`, `ultimate`, `text`, `math`. Math contiene abs/min/max/trunc/floor/ceil per i due float; trigonometria e funzioni trascendenti sono successive. `net` e `http` appartengono alle milestone successive e nell'MVP generano un errore di importazione esplicito.

Le firme normative sono in [ULTIMATE-API.md](ULTIMATE-API.md). I moduli applicativi possono importare altri sorgenti del progetto mediante nomi statici; il bundler risolve un grafo aciclico. `import util` rende disponibili funzioni e costanti esportate dal modulo con nomi qualificati, come `util.funzione(...)` e `util.LIMIT`. Nella 0.1 tutte le funzioni e costanti di un modulo sono visibili mediante tale qualificazione; non introdurre sintassi export o import non qualificati. Ogni modulo ha il proprio spazio di nomi e l'app ha soltanto la entry definita nel §6. Nessun codice eseguito implicitamente all'importazione; niente wildcard o ricerca in directory globali non dichiarate.

I wrapper fanno controlli semplici, preparano i descrittori e invocano syscall. Il kernel resta responsabile dell'isolamento anche per bytecode non prodotto dal compilatore. Non affidare al type checker la protezione di REU, file handle o dispositivi.

### 9.1 Esempio di I/O

```text
import fs
import text
import system

fn main() {
    let data = bytes(32)
    let length = text.copy(data, "C-OS\n")
    let file, err = fs.open("hello.txt", fs.CREATE_TRUNCATE)
    if err != 0 { system.exit(int(err)) }

    let offset: dword = 0
    while offset < length {
        let count, write_error = fs.write(file, data.slice(offset, length - offset))
        offset = offset + count
        if write_error != 0 {
            fs.close(file)
            system.exit(int(write_error))
        }
        if count == 0 {
            fs.close(file)
            system.exit(8)
        }
    }

    let close_error = fs.close(file)
    if close_error != 0 { system.exit(int(close_error)) }
}
```

L'apertura con troncamento è una scelta esplicita del programma. Il driver non deve troncare nuovamente il file quando riapre il backend per alternare le operazioni di più app. L'esempio gestisce risultati parziali; `close` non può garantire la sopravvivenza a un'improvvisa perdita di alimentazione se il firmware/storage non la garantiscono.

### 9.2 Esempio di pixel personalizzati

```text
import ui
import video

fn main() {
    let win, err = ui.open("Pixel", 160, 112)
    if err != 0 { return }
    let pixels = bytes(4096)

    for i in 0..pixels.len {
        pixels[i] = byte((i >> 2) & 15)
    }
    video.blit8(win, 8, 8, pixels, 64, 64)
    ui.present(win)

    while true {
        let event, wait_error = ui.wait(win, ui.FOREVER)
        if wait_error == 0 && event.kind == ui.CLOSE_REQUEST { break }
    }
    ui.close(win)
}
```

`pixels` è memoria dell'app, non un mapping della superficie o del framebuffer. Nessun dettaglio UPIC compare nel programma.

### 9.3 Elenco directory e orologio

```text
import fs
import clock
import system
import text

fn main() {
    let name = bytes(256)
    let dir, open_error = fs.opendir(".")
    if open_error != 0 { system.exit(int(open_error)) }

    let count: word = 0
    while true {
        let info, found, read_error = fs.next(dir, name)
        if read_error != 0 {
            fs.closedir(dir)
            system.exit(int(read_error))
        }
        if !found { break }
        count = count + 1

        if info.kind == fs.FILE && (info.flags & fs.NAME_UNADDRESSABLE) == 0 {
            let filename = text.view(name, dword(info.name_len))
            let details, stat_error = fs.stat(filename)
            if stat_error == 0 && (details.valid & fs.SIZE_VALID) != 0 {
                // details.size e' disponibile, anche per file oltre 64 KiB
            }
        }
    }
    let close_error = fs.closedir(dir)
    if close_error != 0 { system.exit(int(close_error)) }

    let now, time_error = clock.now()
    if time_error == 0 {
        let year = now.year
        // now.month/day/hour/minute/second sono la data civile osservata
    }
}
```

È un esempio di binding e controllo degli errori, da affiancare alla demo grafica prevista in SPEC.md. `name` viene riusato: una vista sul suo contenuto cambia alla successiva fs.next. Se l'app vuole conservare un nome, lo copia in un proprio buffer. Stat può fallire se il file è cambiato dopo la snapshot, senza rendere invalida la lettura della voce precedente.

`clock.now` può restituire EAGAIN mentre il kernel aggiorna la cache. Per attese e intervalli usare sempre system.frame/system.sleep; un cambio dell'ora civile non deve modificare il comportamento dei timer dell'app.

## 10 Grammatica essenziale

La seguente EBNF riassume la struttura; precedenza, newline e regole di tipo sono definiti sopra. `sep` è newline significativo o `;`; i separatori dopo un blocco sono facoltativi.

```text
module     = { import_decl | const_decl | function | sep } ;
import_decl= "import", identifier, sep ;
function   = "fn", identifier, "(", [params], ")", ["->", results], block ;
params     = param, {",", param} ;
param      = identifier, ":", type ;
results    = type | "(", type, {",", type}, ")" ;
block      = "{", {statement | sep}, "}" ;
statement  = let_decl | const_decl | assign | call_stmt | if_stmt
           | while_stmt | for_stmt | return_stmt | "break" | "continue" ;
let_decl   = "let", binding, {",", binding}, "=", expression ;
binding    = identifier, [":", type] | "_" ;
const_decl = "const", identifier, [":", type], "=", expression ;
assign     = lvalue, "=", expression ;
if_stmt    = "if", expression, block, ["else", (block | if_stmt)] ;
while_stmt = "while", expression, block ;
for_stmt   = "for", identifier, "in", expression, "..", expression, block ;
return_stmt= "return", [expression, {",", expression}] ;
lvalue     = identifier | expression, "[", expression, "]" ;
```

Le produzioni semplici richiedono un separatore o la chiusura del blocco. La grammatica completa dei test deve respingere costrutti non supportati, anziché accettarli e ignorarli.

## 11 Compilatore host e formati

Implementazione host consigliata: **Rust**, per compilatore, assembler/disassembler, bundler e reference VM. Iniziare con un piccolo workspace Cargo che condivida definizioni di tipi, ISA e ABI fra i tool; non suddividerlo anticipatamente in molte crate o imporre un framework. Preferire la libreria standard dove pratico; una dipendenza mirata per aritmetica esatta o verifica indipendente è preferibile a risultati numerici approssimati. Pipeline: lexer → parser → risoluzione simboli e tipi → IR semplice → allocazione registri → bytecode/relocazioni → bundler.

Un piccolo parser ricorsivo con precedenze esplicite basta. Non costruire un framework multi-backend. Le ottimizzazioni iniziali sono constant folding, eliminazione di temporanei e mantenimento di contatori/variabili locali in R quando possibile. Il caso semplice non deve rileggere dallo stack REU tutte le variabili a ogni opcode.

Seguire lo spunto QuakeC di una tabella host di operatori, tipi, conversioni e lowering; risolvere gli overload math/text a compilazione. Uno schema condiviso piccolo genera costanti ABI e firme per compiler, reference e kernel. Le costanti float si deduplicano per tipo e bit target; il folding usa COS-NUM-1 dopo ogni operazione, senza aritmetica double host implicita o doppio arrotondamento float32→float24.

Per i sovraccarichi float di math e text.real, il formato viene dal tipo dell'argomento numerico, con i letterali diretti senza formato ancora fissato tipizzati secondo le regole ordinarie. Math.min/max applicano la stessa scelta del tipo comune di un operatore binario. Il tipo selezionato deve essere float24 o float32: gli argomenti soltanto interi richiedono un cast esplicito per questi helper, evitando la scelta ambigua fra due conversioni esatte. Per esempio `math.abs(1)` è errore, `math.abs(1.0)` restituisce float32 e `math.min(a24, 1.0)` restituisce float24. Questa regola riguarda la selezione degli overload; una funzione con un singolo parametro float già dichiarato continua ad ammettere le conversioni implicite esatte.

L'ISA iniziale non ha frame-relative addressing: usare P2 più offset per i load/store nel frame. Int a 32 bit usa coppie di R16 o quattro byte in spill. Gli argomenti delle syscall vengono preparati soltanto alla chiamata, non mantenuti globalmente nei registri riservati.

Float24 occupa tre byte packed, float32 quattro; entrambi possono usare coppie di R16 temporanee. Non riservare un banco di registri float persistente. Il sorgente non può reinterpretare un float24 come puntatore soltanto perché hanno uguale dimensione.

Non eliminare un ciclo infinito solo perché non produce scritture osservabili: il suo avanzamento e il suo consumo di fuel hanno significato per C-OS. Non cambiare i risultati di wrap, cast o bounds con ottimizzazioni aggressive.

Comandi attesi, nomi proposti da rendere reali:

```text
cargo build --release
cargo test --workspace
cargo run --release --bin cosc -- apps/counter/main.cos -o build/counter.cobj
cargo run --release --bin cosdis -- build/counter.cobj
cargo run --release --bin cospack -- manifests/desktop.json --out build/desktop
cargo run --release --bin cosrun -- build/desktop.manifest.json --app counter
```

Sono interfacce di consegna da implementare, non comandi già disponibili. La scelta di Rust riguarda il tooling host; il bytecode C-OS e il kernel 6510 mantengono i propri contratti. Fissare toolchain e dipendenze nei file di build per rendere riproducibili output e test.

Il primo formato `.cobj` può essere JSON host-only: `format="COSOBJ1"`, ABI/versione del compilatore, array di byte per `code` e `data`, `bss_size`, simboli di sezione, entry e relocazioni. Niente parsing JSON sul C64.

Includere anche `numeric_profile="COS-NUM-1"`; il bundler verifica che oggetti, costanti e kernel concordino sul contratto dei due formati.

Relocazioni minime: ABS24 con sezione/offset target e addend; REL16_INSN con origine e destinazione allineate; riferimenti di sezioni per costanti e viste. Verificare overflow, indirizzi fuori arena e branch non allineati al link. Non assegnare puntatori fisici finali durante il parsing del sorgente.

Il bundler conosce le basi delle arene e produce codice finale, seed per i dati inizializzati, manifest e simboli. Se i seed non entrano nella riserva iniziale del sistema, il build fallisce con un report preciso: non sovrascrivere altri dati del pack.

Output indispensabili: listing, mappa indirizzo→file/riga/colonna, dimensione codice/dati/BSS, frame di ogni funzione, stack assegnato, heap disponibile, moduli inclusi e import SDK. In caso di fault, la diagnostica host traduce PID/PC in funzione/riga usando lo stesso build tag.

Le routine di controllo del linguaggio usano TRAP con codici stabili: $1001 RANGE, $1002 BOUNDS, $1003 DIVIDE_BY_ZERO, $1004 OUT_OF_MEMORY, $1005 SHIFT_RANGE, $1006 NUMERIC_INVALID, $1007 FLOAT_OVERFLOW. Sono payload di TRAP, distinti dalle cause native della VM e dagli errori ritornabili delle syscall. NUMERICS.md definisce la traduzione degli errori del servizio numerico.

## 12 Verifica e completamento

- Test lessicali e di precedenza, newline e parsing degli esempi completi.
- Errori di tipo precisi con file/riga/colonna; rifiuto di handle, campi e funzioni inesistenti.
- Aritmetica signed/unsigned ai limiti, cast, divisioni, shift e ordine di valutazione.
- Tipo comune intero, matrice degli operatori e ordine sinistra→destra anche con chiamate negli operandi; rifiuto di uguaglianza su viste/record e di confronti fra handle di tipi diversi.
- Float24/float32: letterali, promozioni, RNE, zero, overflow/underflow, conversioni, testo e corpus bit-exact di NUMERICS.md; nessun doppio arrotondamento involontario.
- Esempi normativi del contesto dei letterali diretti: parentesi/meno unario, narrowing esplicito e assenza di propagazione nelle sottoespressioni.
- Array >64 KiB, ultimo byte valido, slice vuote, indici negativi e overflow.
- str.len, lettura indicizzata e slice senza allocazione; scrittura respinta. Text.decimal ai limiti long/dword, buffer corto senza scritture e valori unsigned oltre 2^31−1.
- Chiamate annidate/ricorsive, risultati multipli e SP identico prima/dopo la chiamata.
- Unico main nel modulo entry, import qualificati e conservazione di P2 nei wrapper che usano MEM_INFO.
- Allocazione azzerata, OOM isolato, buffer riusati senza crescita in un event loop.
- Confronto reference VM/VM 6510 per bytecode generato, includendo cache miss e quantum piccoli.
- Due app C-Script in loop senza yield: entrambe avanzano, input e raster restano serviti.
- Compilazione ed esecuzione degli esempi di UI, pixel, I/O, SID e PCM.
- Binding di Dir/FileInfo/StorageInfo/DateTime/InputState, risultati multipli senza allocazione, coordinate Event negative, campi annidati e riuso del buffer nome; import net/http respinti finché il relativo profilo SDK non è disponibile.
- Build riproducibile a input e versioni fissati; un errore non deve pubblicare un artefatto parziale.

Il linguaggio è completato per l'MVP quando le app dimostrative sono scritte in C-Script e usano l'SDK, senza appoggiarsi a routine native private per aggirare limiti della VM.
