# Numeri frazionari per C-Script

Specifica 0.1, revisione 4 — 10 ottobre 2026. Allegato normativo a [SPEC.md](SPEC.md) e [LANGUAGE.md](LANGUAGE.md). Profilo numerico iniziale: `COS-NUM-1`.

C-Script offre due formati frazionari: **float24**, per dati compatti e calcoli con mantissa corta, e **float32**, per maggiore precisione. `float` è un alias di float32. Il tipo scelto determina rappresentazione e arrotondamento; il backend assembly deve rispettare lo stesso risultato del modello host. Il vantaggio temporale del float24 va misurato, includendo il costo di accesso alla REU e delle chiamate.

## 1 Formati scelti

| Tipo | Byte | Bit significativi nei normali | Precisione decimale indicativa | Interi consecutivi esatti |
|---|---:|---:|---|---|
| `float24` | 3 | 16 | Circa 4–5 cifre significative | Da −65.536 a +65.536 |
| `float32`, alias `float` | 4 | 24 | Circa 6–7 cifre significative | Da −16.777.216 a +16.777.216 |

Entrambi usano un esponente a 8 bit con bias 127. Il minimo positivo normale è 2^-126, circa 1,17549435×10^-38. Il massimo è `(2 − 2^-15) × 2^127` per float24 e `(2 − 2^-23) × 2^127` per float32. Una mantissa corta riduce la precisione, mantenendo lo stesso intervallo degli esponenti normali.

Float32 usa la rappresentazione IEEE binary32. Float24 è un formato C-OS, non uno standard IEEE: segno al bit 23, esponente ai bit 22…15, frazione ai bit 14…0. Il valore normale è `(-1)^sign × (1 + fraction/2^15) × 2^(exponent−127)`. Tutti i valori sono packed little endian.

L'espansione esatta di un float24 normale a binary32 corrisponde allo spostamento dei suoi bit di otto posizioni verso sinistra. La riduzione richiede arrotondamento, non il semplice scarto di un byte. I tre byte di un float24 rappresentano un numero, senza alcuna relazione con i puntatori u24 della VM.

Il profilo supporta zero e numeri finiti normali. È una semantica limitata, **non una dichiarazione di conformità IEEE 754 completa**:

- Ogni operazione arrotonda alla precisione del tipo risultato con round-to-nearest, ties-to-even, abbreviato RNE.
- Il risultato viene prima arrotondato al formato destinazione; se resta subnormale viene trasformato in +0. Un valore che si arrotonda al minimo normale deve sopravvivere.
- Input subnormali e −0, anche forniti da bytecode manuale, vengono interpretati come +0 all'ingresso delle operazioni numeriche.
- Gli output zero hanno sempre tutti i bit zero. Non esistono modalità di arrotondamento o flag numerici globali modificabili dalle app.
- Input con esponente 255, inclusi NaN e infiniti, sono invalidi. Overflow produce errore; divisione per zero produce errore. Il runtime del linguaggio traduce gli errori nei fault definiti sotto.

Byte, word, int, dword e long conservano la propria aritmetica intera. Dimensioni, indirizzi, handle, indici, fuel e timer continuano a usare interi.

## 2 Float16 e fixed point

Un terzo formato binary16 avrebbe 2 byte, 11 bit significativi, circa 3 cifre significative, massimo 65.504 e minimo normale 2^-14. Resta candidato successivo: nel profilo senza subnormali il limite inferiore è circa 0,000061. A valori intorno a 320, il passo fra rappresentabili sarebbe 0,25; float24 offre un passo di 1/128 e float32 di 1/32.768. Questi sono passi numerici, non misure di fluidità della UI.

La prima implementazione include float24 e float32. Evitare il costo di tre backend prima di avere app e misure che giustifichino binary16. Le routine half di Mad-Pascal costituiscono un riferimento concreto di aritmetica a mantissa ridotta; il codice di addizione/prodotto esaminato non è un backend RNE direttamente riutilizzabile. [Libreria f16](https://github.com/tebe6502/Mad-Pascal/blob/master/lib/f16.pas).

Il fixed point, ad esempio Q16.16, è un'alternativa per interpolazioni con intervallo noto. Offre un passo uniforme ma non l'ampio intervallo dinamico dei float. Può essere una libreria successiva; non aggiungere ora un terzo tipo frazionario chiamandolo float.

## 3 Sintassi e conversioni

```text
fn main() {
    let speed: float24 = 0.125
    let position: float24 = 12.5
    position = position + speed

    let measured: float32 = 1234.56789
    let mean = measured / 3.0
    let precise_position = float32(position)
    let compact_mean = float24(mean)
    let pixel = int(position) // troncamento verso zero, con controllo range
}
```

Letterali frazionari: cifre, punto e cifre, eventualmente seguiti da `e`/`E`, segno opzionale ed esponente decimale; è ammesso anche `1e3`. Esempi validi: `0.5`, `1.0`, `1e-3`, `1.25E+2`. Richiedere le cifre prima e dopo il punto quando presente; `1..10` resta un intervallo intero, senza ambiguità con `1.`. Underscore soltanto fra cifre.

L'inferenza segue LANGUAGE.md §4.1 dal basso verso l'alto. Un letterale diretto è un token numerico racchiuso eventualmente soltanto da parentesi e meno unario; i nomi di costanti e le espressioni composte sono già tipizzati. Senza contesto un letterale frazionario ha tipo float32. Una dichiarazione, assegnazione, parametro, risultato atteso o cast applicato direttamente al letterale può richiedere float24. In un operatore con un operando float già tipizzato e un letterale diretto, quest'ultimo assume il formato dell'altro operando. Se entrambi sono letterali diretti, prendono il tipo senza contesto. Il tipo atteso all'esterno non viene propagato nei loro operatori binari.

Con `a24: float24`, valgono questi esempi normativi:

| Sorgente | Semantica |
|---|---|
| `let x: float24 = (-0.5)` | Letterale diretto arrotondato a float24 |
| `let x: float24 = 1.0 + 2.0` | Errore: somma float32 assegnata a float24 senza cast |
| `float24(1.0 + 2.0)` | Somma float32, poi cast RNE a float24 |
| `a24 + (1.0 + 2.0)` | Somma interna float32 e risultato esterno float32 |
| `a24 + 1.0` | Letterale e somma float24 |
| `float24(1.0) + 2.0` | Somma float24 perché il primo operando è già tipizzato |

Gli interi senza punto/esponente mantengono le regole del linguaggio quando nessun contesto diretto richiede un float. Non cambiare questi tipi dopo il constant folding.

Conversioni implicite aggiuntive: byte/word/int verso entrambi i float; float24 verso float32. Sono esatte per tutti i valori del tipo sorgente. Long/dword verso float richiedono un cast, perché possono perdere unità. Float32 verso float24 richiede un cast RNE. Un cast che racchiude un'espressione già tipizzata converte il risultato: `float24(a32 + b32)` esegue prima la somma float32.

Il contesto può fissare il formato di un letterale frazionario o convertire un letterale intero isolato; non trasforma in floating point un'espressione composta da soli interi. `float24(1 / 2)` e `let x: float24 = 1 / 2` producono zero: prima si esegue la divisione intera, poi si converte il risultato. Per la divisione frazionaria scrivere `1.0 / 2.0`.

Le operazioni miste float24/float32 promuovono a float32. Non restringere implicitamente un risultato float32 per assegnarlo a float24. Gli operatori ammessi sono `+ - * /`, meno unario e i sei confronti, che producono bool. `%`, bitwise e shift rimangono interi. `1 / 2` mantiene la divisione intera; `1.0 / 2.0` produce 0,5.

Float→integer tronca verso zero e controlla il range del risultato troncato prima di scriverlo; nessun wrap o comportamento indefinito del compilatore host. `int(-3.75)` vale −3; `byte(-0.5)` vale 0; `byte(-1.0)` è RANGE. Conversioni a 8/16 bit usano prima il risultato signed/unsigned a 32 bit, poi il controllo esistente.

I cast fra formati e le costanti vengono arrotondati direttamente al formato richiesto. Il compiler host deve partire dal decimale esatto del token, non da un double già arrotondato. Non cambiare associazione, fondere prodotto/somma o mantenere precisione nascosta oltre un'operazione del sorgente.

## 4 Libreria minima

`math` è un modulo statico. Le funzioni seguenti sono sovraccarichi risolti a compilazione per float24 e float32, senza dispatch dinamico:

| Funzione | Risultato |
|---|---|
| `math.abs(x)` | Stesso tipo di x, valore assoluto |
| `math.min(a, b)`, `math.max(a, b)` | Tipo comune dopo le conversioni ordinarie |
| `math.trunc(x)` | Stesso tipo, frazione eliminata verso zero |
| `math.floor(x)`, `math.ceil(x)` | Stesso tipo, intero matematico inferiore/superiore |
| `text.real(dst: bytes, value: float24/float32, digits: byte) -> (str, word)` | Formattazione con 1…9 cifre significative, buffer ≥24 byte |
| `text.parse_float(src: str) -> (float32, word)` | Parsing nel formato normale del linguaggio |
| `text.parse_float24(src: str) -> (float24, word)` | Parsing diretto nel formato compatto |

Il formato degli overload viene dal tipo dell'argomento numerico, non dal risultato atteso della chiamata. I letterali diretti seguono le regole ordinarie; math.min/max scelgono il tipo comune come un operatore binario, inclusa la regola del letterale diretto accanto a un operando tipizzato. Il tipo così ottenuto deve essere float24 o float32. Con soli argomenti interi richiedere un cast esplicito: `math.abs(1)` è errore, `math.abs(1.0)` sceglie float32 e `math.min(a24, 1.0)` sceglie float24. Text.real applica la stessa regola al parametro value. Non introdurre overload interi di math come conseguenza accidentale delle conversioni implicite.

Text.real arrotonda in decimale ties-to-even al numero richiesto di cifre significative; usa forma fissa se l'esponente decimale, dopo tale arrotondamento, è tra −4 e digits−1 inclusi, altrimenti forma scientifica. Rimuove gli zeri frazionari finali e il punto rimasto vuoto; zero diventa `0`. Separatore `.`, esponente `e` con segno e almeno due cifre, nessuna dipendenza dalla locale. L'output è length-delimited. Verificare nell'ordine digits 1…9, capacità dst ≥24 e validità numerica: ERANGE per i primi due errori, EDOM per un input non finito. Subnormali e −0 seguono la canonicalizzazione del profilo. Su errore la vista risultato è vuota e dst resta invariato. Nove cifre permettono il round-trip di float32, sei quello di float24; le cifre stampate non aumentano la precisione del valore.

I parser accettano un segno iniziale opzionale, decimali interi o frazionari e un esponente opzionale, senza underscore, spazi o caratteri finali. Il punto richiede cifre su entrambi i lati: `.5` e `1.` sono invalidi, `0.5` e `1.0` validi. Lunghezza da 1 a 63 byte; segnalare EINVAL per sintassi e ERANGE per lunghezza/overflow. Restituire zero con errore, senza parsing parziale. RNE e underflow seguono il formato richiesto. Formattazione e parsing devono gestire interamente l'intervallo del tipo.

Limitare il costo anche per esponenti testuali enormi. Accumularli con saturazione e classificare il risultato prima di costruire potenze di dieci o avviare loop di scala; il lavoro non può essere proporzionale al valore numerico dell'esponente. Dopo la verifica completa della sintassi, zero con qualsiasi esponente resta zero; overflow evidente di un valore non nullo dà ERANGE, underflow evidente dà +0. Il compiler host applica la stessa regola, con un limite di 128 byte per token numerico frazionario, underscore inclusi.

Le conversioni testuali iniziano come helper bytecode con workspace statico nel frame dell'app e cicli soggetti a fuel. Evitare allocazioni a ogni conversione. I loro byte in REU, stack, chiamate numeriche e tempi fanno parte del report. Il nucleo assembly residente comprende soltanto aritmetica, confronti e conversioni numeriche; un'accelerazione testuale successiva richiede la stessa qualificazione temporale.

Sqrt, trigonometria, logaritmi, esponenziali e potenze generali sono estensioni successive. Il tipo float non implica di importare una libreria matematica completa in RAM locale.

## 5 ABI del servizio numerico

Riservare la syscall esadecimale **30 NUM_OP**. È un servizio del kernel indipendente dai dispositivi Ultimate. Entrambi i formati fanno parte dell'MVP: non sono capability hardware opzionali.

- R1: operazione nei bit 7…0, formato nei bit 15…8; formato 0=float32, 1=float24, altri invalidi.
- R2/R3: operando A, low16/high16. R4/R5: operando B, low16/high16, zero per operazioni unarie.
- Float24 occupa i 24 bit bassi; gli 8 alti devono essere zero. Gli input integer32 usano tutti i 32 bit. Non convalidare un intero come rappresentazione float.
- R0 al ritorno: stato. R2/R3: risultato low16/high16, azzerato su errore. Gli altri R e tutti i P sono preservati.
- Le operazioni binarie calcolano A op B. FCMP restituisce −1/0/+1 in R2 signed16 e R3=0; i wrapper generano bool con confronti interi.

| Op | Nome | Significato del formato selezionato |
|---|---|---|
| 00 | FADD | Entrambi gli input e il risultato |
| 01 | FSUB | Entrambi gli input e il risultato |
| 02 | FMUL | Entrambi gli input e il risultato |
| 03 | FDIV | Entrambi gli input e il risultato |
| 04 | FCMP | Entrambi gli input |
| 05 | FROM_I32 | Formato del risultato; A è i32 |
| 06 | FROM_U32 | Formato del risultato; A è u32 |
| 07 | TO_I32 | Formato di A; risultato i32 |
| 08 | TO_U32 | Formato di A; risultato u32 |
| 09 | FTRUNC | Formato di A e del risultato |
| 0A | FFLOOR | Formato di A e del risultato |
| 0B | FCEIL | Formato di A e del risultato |
| 0C | F24_TO_F32 | Richiede formato 0; A è float24, output float32 |
| 0D | F32_TO_F24 | Richiede formato 1; A è float32, output float24 |

Per 0C/0D convalidare A secondo il tipo di ingresso indicato nella tabella: il formato in R1 descrive il risultato. In particolare il byte alto di A in F32_TO_F24 può essere non nullo. Per tutte le operazioni unarie R4/R5 devono essere zero.

Operazione/formato/campi invalidi: EINVAL. Rappresentazione non finita: nuovo stato 22 EDOM. Denominatore zero dopo la normalizzazione: nuovo stato 23 EDIVZERO. Overflow e conversione fuori range: ERANGE. Convalidare prima gli operandi, poi il denominatore, poi eseguire il calcolo. Non sono errori gli arrotondamenti ordinari o l'underflow a zero.

I wrapper di operatori/cast traducono EDOM in TRAP `$1006 NUMERIC_INVALID`, EDIVZERO in `$1003 DIVIDE_BY_ZERO`, ERANGE aritmetico o da riduzione float in `$1007 FLOAT_OVERFLOW`, ERANGE da cast integer in `$1001 RANGE`. Gli errori del compilatore su espressioni costanti sono diagnosticati a build time. I parser restituiscono gli errori documentati, permettendo all'app di correggere l'input.

Meno unario e abs possono usare operazioni bytecode sui bit del valore già valido, canonicalizzando zero. Non servono registri F persistenti o nuovi opcode del dispatcher. Un valore float32 usa due R16 o quattro byte nel frame; float24 tre byte nel frame e, quando serve, due R16 con la parte alta azzerata.

## 6 Scheduling e memoria del backend

NUM_OP usa l'unica coda di lavori nativi esistente. SYSCALL costa un opcode e registra una sola continuazione; i pezzi matematici sono addebitati al tempo nativo del proprietario, a rotazione con gli altri lavori. Una syscall matematica completata subito, o sospesa per una fase interna, non ricarica il fuel. Per NUM_OP preservare il residuo fino alla normale fine del quantum: è lavoro CPU, non un'attesa di un dispositivo esterno.

La prima scelta implementativa è una routine indivisibile, ammessa soltanto dopo averne qualificato il costo massimo comprensivo del bridge e verificato che entri nella finestra disponibile, guard time incluso. Se ora non entra ma entra nella prossima finestra utile, rinviare l'intera operazione. Introdurre continuazioni interne soltanto per le operazioni il cui costo massimo non entra nella finestra di servizio qualificata: in quel caso suddividerle in fasi esplicite, per esempio allineamento, iterazioni del prodotto/divisione e arrotondamento. Nessun frame nativo resta sullo stack hardware tra i turni. Un algoritmo con un numero finito di iterazioni non è automaticamente abbastanza breve per il raster.

Operandi, formato, accumulatore parziale, carry/sticky e cursore della fase appartengono al lavoro del processo. Il kernel può usare uno scratch ZP comune solo durante l'esecuzione di un pezzo; salvare tutto ciò che resta vivo prima di servire un altro proprietario. Non sovrapporre FAC/ARG o registri temporanei di una libreria esterna ai registri VM o allo scratch UPIC.

Il costo comprende bridge, controlli, spill/reload, salvataggio del contesto e accesso REU. Kill annulla il lavoro e rilascia lo scratch, senza pubblicare un risultato a un processo terminato. Ogni app ha al massimo un lavoro bloccante pendente, come negli altri servizi.

Obiettivo iniziale da qualificare: nucleo residente dei due formati, conversioni numeriche e bridge entro **4 KiB complessivi**, inclusi nel budget locale da 20 KiB. Non è una dimensione già dimostrata. Riportare separatamente ZP, RAM scratch, contesti dei lavori in REU e helper testuali. Se il nucleo eccede, condividere percorsi e spostare helper non critici in bytecode; non eliminare un formato o cambiare precisione senza aggiornare esplicitamente la specifica.

Float24 deve avere un vero percorso con mantissa a 16 bit: prodotto 16×16 e divisione alla precisione necessaria, con bit di guardia e sticky. Condividere unpack, segni, esponenti, errori e scheduling dove conviene; confrontare specializzazione con un nucleo parametrico. Compilare ogni operazione float24 come float32 più compressione non soddisfa l'obiettivo di accelerazione e può introdurre doppio arrotondamento.

## 7 Fonti e scelta del backend

| Riferimento | Riscontro e impiego in C-OS |
|---|---|
| [XC-BASIC 3](https://xc-basic.net/doku.php?id=v3:datatypes) | Float di 4 byte, circa 6–7 cifre. Utile l'affiancamento agli interi; il nome DECIMAL indica BCD per interi 0…9999, non un tipo frazionario. |
| [Math pack XC-BASIC](https://github.com/neilsf/xc-basic3/blob/55014f0f6a2dfa2d40e377102f4da6b764a1e788/lib/math/_fplib.asm) | Seleziona BYTES_FP=4 e tre byte di mantissa; usa FAC/ARG globali e deriva dal math pack MS BASIC. Formato diverso da binary32 e arrotondamento da verificare. Fonte di algoritmi e conversioni, non libreria da collegare invariata. |
| [LLVM-MOS add](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/addsf3.S), [mul](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/mulsf3.S), [div](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/divsf3.S) | Assembly 6502 con RNE e trattamento dei valori speciali. Primo candidato per float32 e riferimento per derivare il percorso corto; le routine originali non includono il fuel C-OS. |
| [Oscar64 runtime](https://github.com/drmortalwombat/oscar64/blob/main/include/crt.c) e [manuale](https://github.com/drmortalwombat/oscar64/blob/main/oscar64.md) | Altro backend binary32 orientato al 6502. Il manuale esclude NaN; gli shift esaminati non dimostrano il nostro contratto RNE. Utile per confronto di algoritmi e dimensioni, non sostituzione senza test. |
| [Woz e correzioni Rankin](https://github.com/jefftranter/6502/blob/master/asm/wozfp/README.txt) | Esempio storico compatto a 4 byte con mantissa in complemento a due. Richiede un formato diverso; utile per studio, non per cambiare silenziosamente l'ABI numerica. |
| [Microsoft BASIC M6502](https://github.com/microsoft/BASIC-M6502) | Math pack storico con precisione configurabile; possibile fonte primaria alternativa. La dimensione dell'intero interprete non misura il solo costo dei float. |
| [SoftFloat per 6502](https://github.com/rweather/berkeley-softfloat-3-6502) | Candidato a oracolo host per binary32. Il port C non prova velocità o ingombro adeguati al kernel C-OS. |

Fissare commit e licenze nel report prima di integrare codice. XC-BASIC è MIT a livello di repository, ma il file matematico reca un avviso BSD a due clausole: conservare la provenienza specifica. LLVM-MOS dichiara Apache-2.0 con LLVM exception; Microsoft BASIC-M6502 è MIT; per Oscar64 esaminare GPL e condizioni dei file effettivamente importati. Per i listing storici Woz non dedurre una licenza dal semplice accesso pubblico.

Non è stato individuato in questa ricognizione un backend NMOS pronto che garantisca esattamente il formato float24 e il profilo qui definiti. La specializzazione e i test sono lavoro della milestone numerica. Nessun rapporto di velocità fra questi candidati è assunto senza misure omogenee.

## 8 Spunti adottati da QuakeC

QuakeC suggerisce una tabella host unica di operatori, tipi e lowering, deduplicazione delle costanti per rappresentazione target e builtins risolti staticamente. Usare uno schema piccolo e leggibile per generare ID e firme condivisi fra compiler/reference VM/kernel, includendo il profilo numerico. Conservare listing, nomi di funzione e source map fuori dalla build minima. [Compilatore originale](https://github.com/id-Software/Quake-Tools/blob/master/qcc/pr_comp.c), [generazione del contratto condiviso](https://github.com/id-Software/Quake-Tools/blob/master/qcc/qcc.c).

La VM Quake conta statement, offre profiling e termina dopo un limite di runaway; quel controllo non sospende/riprende una funzione. C-OS conserva fuel e continuazioni proprie. Nelle build diagnostiche contare chiamate e costo degli helper float, distinguendo opcode da tempo nativo. [Esecutore originale](https://github.com/id-Software/Quake/blob/master/WinQuake/pr_exec.c).

Mantenere gli interi espliciti, il bytecode da quattro byte e i frame guest C-Script. Il modello centrato su float/vettori, gli statement da otto byte e i locali salvati dalla VM Quake non sono requisiti di C-OS. [Tipi e statement Quake](https://github.com/id-Software/Quake/blob/master/WinQuake/pr_comp.h).

## 9 Verifiche richieste

Il modello host usa interi e rapporti esatti per produrre le operazioni del formato scelto; può usare un oracolo binary32 verificato per confronto indipendente. Esportare un corpus comune di input, risultati in bit ed errori. Il compiler, il constant folder e il backend 6510 devono coincidere, compreso il confine fra normali e subnormali.

Il tooling Rust consigliato in LANGUAGE.md deve implementare questa semantica senza delegare il folding ai normali f32/f64 host. Un oracolo ausiliario indipendente, per esempio Python con Fraction, può generare o verificare il corpus esatto. Condividere il corpus non significa usare la stessa implementazione come unico test di se stessa; la scelta delle librerie host non modifica COS-NUM-1.

Copertura minima:

1. Encoding little endian: zero, ±1, 0,5, massimi, minimi normali, input subnormali, −0, NaN/Inf e bit alti non nulli in input float24.
2. Quattro operazioni, cancellazione quasi completa, esponenti molto diversi, metà esatte ties-to-even, overflow e divisione per zero per entrambi i formati.
3. Confini integer32, conversioni signed/unsigned, troncamento prima del range check, promozioni, cast di restringimento ed errori di tipo.
4. Risultato appena sotto il minimo normale che arrotonda al minimo normale; risultato ancora subnormale che diventa zero.
5. Constant folding identico al runtime, senza riassociazione o precisione nascosta; letterali float24 convertiti direttamente dal decimale.
   Verificare inoltre gli esempi di contesto del §3: parentesi e meno unario conservano il letterale diretto, gli operatori binari fissano il tipo prima del contesto esterno e il folding non elimina errori di narrowing.
6. Test specifico di doppio arrotondamento: in float24 `1.682830810546875 × 1.40277099609375` deve produrre `2.36065673828125`. Passare prima da un prodotto binary32 arrotondato produce invece `2.360595703125`: quel percorso va respinto.
7. Parsing invalido/oltre quota, dst corto, formattazione ai confini decimali, round-trip a sei/nove cifre e workspace senza crescita dell'heap.
8. Due app alternano i formati con quantum piccolo e cache miss; risultati e scratch restano indipendenti. Kill e sospensione a ogni fase del lavoro.
9. Loop float senza yield insieme a input/UI, file I/O e PCM. Misurare latenza, scadenze raster e tempo nativo per processo.

Il benchmark riporta separatamente +, −, ×, ÷, compare, cast e testo: dimensione del nucleo linkato, ZP, scratch, cicli minimi/massimi osservati, limite temporale qualificato, costo end-to-end con REU e throughput dentro il calendario UPIC. Riportare la differenza float24/float32 sulla stessa build. Se float24 risparmia soltanto memoria, dichiararlo; l'ABI a tre byte da sola non prova un aumento di velocità.

## 10 Consegna

M4a produce compiler e ABI di chiamata già previsti. M4b aggiunge i due float, NUM_OP, helper testuali e corpus host/6510 prima della qualificazione completa. Il manifest e ogni oggetto host riportano `numeric_profile="COS-NUM-1"`; il bundler rifiuta combinazioni incompatibili. ABI iniziale 1 resta il contratto di una prima implementazione non ancora distribuita; future modifiche numeriche incompatibili richiedono un nuovo profilo e relativa verifica.

La consegna comprende fonti fissate, licenze, test riproducibili e report di dimensioni/timing. Il supporto numerico è completo quando entrambi i formati funzionano nelle app C-Script e sotto carico concorrente, con i limiti pubblicati.
