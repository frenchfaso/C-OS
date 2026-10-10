# SDK e servizi Ultimate per C-OS

Specifica 0.1, revisione 4 — 10 ottobre 2026. Allegato normativo a [SPEC.md](SPEC.md) e [LANGUAGE.md](LANGUAGE.md). ABI iniziale 1; nessuna implementazione precedente da migrare.

Le app devono poter usare video, file e directory, storage, orologio, SID e Ultimate Audio con poche chiamate. Le API nascondono UCI, indirizzi dei dispositivi, DMA, sincronizzazione e differenze di firmware. Ogni operazione rispetta isolamento e scheduling del kernel; il dispositivo non viene assegnato come intervallo I/O direttamente scrivibile dall'app.

I nomi, i layout e gli ID seguenti sono proposte normative per l'implementazione C-OS, **non** API già presenti nel firmware Ultimate.

Priorità dei servizi Ultimate:

| Consegna | API |
|---|---|
| MVP, M6a | File esistenti + stat, directory, mkdir/rename/remove; scoperta storage e lettura RTC |
| MVP, M6b | SID e Ultimate Audio già previsti |
| Dopo MVP, N1 | Client TCP/UDP, con limiti di attesa e isolamento dei socket |
| Dopo MVP, N2 | HTTP e accesso JSON delegati al firmware, dopo prove del backend |
| Successive | Palette, immagini disco, SoftIEC e strumenti amministrativi |

Le sezioni 1–9 sono il contratto MVP. La sezione 10 delimita le estensioni: firme proposte da qualificare prima di assegnare opcode/ABI definitivi.

## 1 Regole comuni

1. Argomenti e buffer sono valori guest; puntatori lineari REU u24, lunghezze u32. Nessun puntatore 6510 dell'app.
2. Gli handle identificano una risorsa, il proprietario e il tipo. Non sono indici hardware utilizzabili senza verifica.
3. Un processo può avere una sola syscall bloccante in corso. La richiesta conserva una continuazione del kernel e sospende soltanto quel processo.
4. Nessun busy wait lungo, nessun loop nativo proporzionale a una dimensione non limitata, nessuna attesa del firmware con il raster sospeso.
5. Un batch viene validato prima degli effetti evitabili. Le operazioni su dispositivi possono fallire dopo effetti parziali: dichiarare conteggi e semantica dell'errore.
6. Dati letti da driver/hardware devono includere le ultime scritture VM; dati scritti dal driver devono essere visibili alle LOAD successive. Usare l'unico protocollo di coerenza REU del kernel.
7. Kill/fault/uscita rilasciano tutte le risorse. Il cleanup che attende un dispositivo vive nel kernel e non riprende il bytecode terminato.

I servizi restituiscono i codici di stato definiti in SPEC.md. I wrapper C-Script restituiscono `valore, errore` oppure il solo `errore`. Un successo è `0`; un servizio presente ma non abilitato restituisce ENODEV/ENOTSUP, senza simulare un successo.

Gli ID in questo documento sono esadecimali. Tutti i descrittori guest sono little endian, packed; i campi riservati devono essere zero. Un output non descritto non può contenere vecchi registri/dati del kernel.

## 2 Superficie dell'SDK C-Script

### 2.1 Sistema e UI

| Firma | Comportamento |
|---|---|
| `system.exit(code: int)` | Termina il processo, non ritorna |
| `system.sleep(frames: word) -> word` | Attesa in frame; zero cede il turno |
| `system.frame() -> dword` | Contatore monotono modulo 2^32 |
| `ui.open(title: str, width: word, height: word) -> (Window, word)` | Finestra centrata, X pari; misure esterne |
| `ui.close(win: Window) -> word` | Chiude la finestra |
| `ui.title(win: Window, title: str) -> word` | Modifica il titolo, massimo 15 byte |
| `ui.wait(win: Window, timeout: word) -> (Event, word)` | Evento o EAGAIN; 0=poll, 65535=attesa indefinita |
| `ui.input_state(win: Window) -> (InputState, word)` | Pulsanti, modificatori e puntatore relativo al client |
| `ui.clear(win: Window, color: byte) -> word` | Riempie il client |
| `ui.fill(win: Window, x: int, y: int, w: word, h: word, color: byte) -> word` | Rettangolo clippato |
| `ui.frame(win: Window, x: int, y: int, w: word, h: word, color: byte) -> word` | Bordo interno di un pixel |
| `ui.text(win: Window, x: int, y: int, value: str, fg: byte, bg: byte) -> word` | Testo opaco, massimo 255 byte per chiamata |
| `ui.present(win: Window) -> word` | Attende la presentazione del lavoro accettato |

`ui.FOREVER=65535`. Colori: BLACK=0, WHITE=1, DARK_GRAY=11, GRAY=12, LIGHT_GRAY=15. I wrapper non limitano i colori client a questi cinque; la shell invece deve farlo.

Le costanti SDK sono tipizzate nel binding, non semplici `int` inferiti: colori, tipi evento e flag Event sono byte; FOREVER, modi file, capability e codici di errore sono word; i keycode sono int; maschere pulsanti/modificatori sono word. Le altre costanti di record hanno il tipo del campo corrispondente (per esempio FileInfo.kind byte e FileInfo.flags word). Usare nomi distinti nel modulo ui: `KEYCODE_LEFT` per il tasto, `BUTTON_LEFT` per il pulsante, `MOD_SHIFT` per il modificatore; tutti i tasti, pulsanti e modificatori elencati sotto seguono rispettivamente i prefissi KEYCODE_, BUTTON_ e MOD_. I tipi evento conservano nomi come `ui.KEY_DOWN` e `ui.CLOSE_REQUEST`; `ui.REPEAT` è il flag byte. Il compilatore verifica queste firme come quelle delle funzioni.

`Event` corrisponde esattamente al record di SPEC.md: `kind: byte`, `flags: byte`, `window: Window`, `arg0: int`, `arg1: int`, `arg2: word`, `frame: dword`, `reserved: word`. Le coordinate signed mantengono lo stesso layout di 16 byte. Tipi evento: 1 POINTER_MOVE, 2 BUTTON_DOWN, 3 BUTTON_UP, 4 KEY_DOWN, 5 KEY_UP, 6 FOCUS, 7 BLUR, 8 CLOSE_REQUEST, 9 INPUT_RESET. Il record viene azzerato dal wrapper se l'attesa restituisce errore, senza interpretare campi non inizializzati.

Per POINTER_MOVE/BUTTON: arg0=x client, arg1=y client, arg2=maschera dei pulsanti della cattura dopo la transizione, LEFT=1 e RIGHT=2; senza cattura la maschera è zero. BUTTON_DOWN nel client avvia la cattura per quella finestra: movimenti e transizioni successive le arrivano anche fuori dal client, con coordinate signed, fino al rilascio dell'ultimo pulsante, BLUR, nascondimento o chiusura. Per KEY: arg0=codice normalizzato, arg1=ASCII del testo attuale oppure zero se il tasto non produce testo, arg2=modificatori; SHIFT=1, CONTROL=2, COMMODORE=4. `flags` ammette soltanto bit0 REPEAT su KEY_DOWN; è zero negli altri casi. FOCUS/BLUR/CLOSE_REQUEST/INPUT_RESET hanno argomenti zero. I comandi globali della shell sono consumati dal kernel e non vengono duplicati nella coda dell'app.

La tabella dei codici tasto MVP è unica per kernel e SDK; il manifest non la ridefinisce: `0x20…0x7E` per tasti imprimibili, con lettere maiuscole e simbolo base senza Shift; `0x100` RETURN, `0x101` BACKSPACE, `0x102` INSERT, `0x103` LEFT, `0x104` RIGHT, `0x105` UP, `0x106` DOWN, `0x107` HOME, `0x108` CLEAR, `0x109` RUN_STOP; `0x110…0x117` per F1…F8 in ordine; `0x120` SHIFT, `0x121` CONTROL, `0x122` COMMODORE. Il byte ASCII in arg1 riflette invece il testo effettivo, inclusi Shift e modalità della tastiera. I tasti funzione fisici F1/F3/F5/F7 con Shift producono F2/F4/F6/F8, quindi Shift+F5 produce il codice F6; Shift+RIGHT e Shift+DOWN producono LEFT e UP. Shift+BACKSPACE produce INSERT e Shift+HOME produce CLEAR. Conservare il codice scelto al key-down fino al relativo key-up, anche se Shift viene rilasciato prima. Gli altri codici sono ignorati nell'MVP; nessuno scancode hardware passa alle app.

`ui.wait` passa Window in R1 a EVENT_WAIT: il kernel verifica proprietario e finestra viva prima di consumare un evento o sospendere il processo. Un handle chiuso restituisce EBADF anche dopo la creazione di una nuova finestra. `ui.input_state` usa INPUT_STATE con R0=Window; il kernel restituisce R1=pulsanti, R2=modificatori, R3=x client, R4=y client. Il wrapper costruisce `InputState`, 8 byte packed: `buttons: word` a 0, `modifiers: word` a 2, `x: int` a 4, `y: int` a 6; su errore il record è zero. Le coordinate possono essere esterne al client e non vengono clippate.

InputState rappresenta lo stato consegnabile a quella finestra, non tutti i pulsanti fisicamente premuti: `buttons` è zero se la finestra non possiede la cattura; `modifiers` è zero se non ha il focus. Le coordinate sono comunque quelle attuali relative al client. In questo modo leggere lo stato dopo BLUR non ripristina una pressione il cui rilascio andrebbe altrove.

INPUT_RESET o BLUR impongono all'app di cancellare tutti i propri tasti mantenuti logicamente premuti; BLUR cancella anche pulsanti e interazioni client. Dopo INPUT_RESET l'app può rileggere pulsanti, modificatori e puntatore con `ui.input_state`; la 0.1 non offre una bitmap dei tasti. Questo contratto evita che la perdita di KEY_UP in una coda piena lasci un tasto bloccato nell'app. Flag pendenti, coalescing del focus e ordine di consegna seguono SPEC.md §13.2.

Le prime primitive sono wrapper immediati su GFX_SUBMIT. I wrapper, compresi i blit video, azzerano ogni record di 16 byte prima di compilare i campi usati: i temporanei sullo stack non sono implicitamente zero. L'accesso a batch è `ui.submit(win: Window, commands: bytes, count: word) -> word`: verifica `1 <= count <= 16` e almeno `16*count` byte, usando il formato già definito. I helper più comodi per costruire batch possono essere aggiunti alla libreria dopo avere misurato le app semplici. Non serve un albero retained di widget.

### 2.2 Video

| Firma | Comportamento |
|---|---|
| `video.info() -> (VideoInfo, word)` | Risoluzione, formati sorgente e capacità |
| `video.client_size(win: Window) -> (word, word, word)` | Larghezza, altezza client, errore |
| `video.blit8(win: Window, x: int, y: int, pixels: bytes, w: word, h: word) -> word` | Sorgente lineare INDEX8, stride=w |
| `video.blit4(win: Window, x: int, y: int, pixels: bytes, w: word, h: word) -> word` | Sorgente packed, stride=ceil(w/2) |

Il wrapper valida che la vista contenga almeno i byte richiesti, poi il kernel valida di nuovo l'intervallo guest. Un blit non modifica il buffer sorgente; la sua vita deve coprire la chiamata bloccante. Clipping e conversione sono nativi e suddivisi in pezzi limitati.

**Non esiste `video.framebuffer()` nella 0.1.** Un buffer creato con `bytes()` appartiene all'app e appare sullo schermo soltanto dopo il blit. Il formato interno tiled/packed e il framebuffer UPIC non sono visibili. Niente registri VIC, routine raster, sprite hardware o indirizzi UPIC nell'ABI.

Una futura estensione potrà restituire `{ptr, width, height, stride, format}` per un framebuffer logico, con acquisizione, danno/presentazione e rilascio espliciti. Potrà essere una superficie dell'app in REU; non dovrà promettere alias con lo scanout fisico. Non riservare oggi un mapping o imporre costi di coerenza per questa possibilità.

### 2.3 File

| Firma | Comportamento |
|---|---|
| `fs.open(path: str, mode: word) -> (File, word)` | File relativo alla directory dati dell'app |
| `fs.read(file: File, dst: bytes) -> (dword, word)` | Byte letti e stato; zero con successo = EOF o richiesta vuota |
| `fs.write(file: File, src: bytes) -> (dword, word)` | Byte confermati scritti e stato |
| `fs.seek(file: File, position: dword) -> word` | Posizione assoluta nell'intervallo 0…dimensione, EOF incluso |
| `fs.tell(file: File) -> (dword, word)` | Posizione logica corrente |
| `fs.size(file: File) -> (dword, word)` | Dimensione del file |
| `fs.close(file: File) -> word` | Rilascia l'handle; controllare eventuale errore del backend |
| `fs.stat(path: str) -> (FileInfo, word)` | Tipo, attributi e metadati disponibili |
| `fs.opendir(path: str) -> (Dir, word)` | Crea un elenco in REU; `"."` indica la root dati dell'app |
| `fs.next(dir: Dir, name: bytes) -> (FileInfo, bool, word)` | Una voce; bool=false con errore=0 indica fine elenco |
| `fs.closedir(dir: Dir) -> word` | Libera l'elenco e invalida l'handle |
| `fs.mkdir(path: str) -> word` | Crea una directory, senza creare automaticamente gli antenati |
| `fs.rename(old_path: str, new_path: str) -> word` | Rinomina entro la root dell'app; destinazione già esistente = EEXIST |
| `fs.remove(path: str) -> word` | Elimina un singolo file; una directory restituisce EISDIR |

Modalità iniziali: READ=1, READ_WRITE=2, CREATE_NEW=3, CREATE_TRUNCATE=4. Sono enum C-OS, **non flag UCI da inoltrare senza traduzione**. READ/READ_WRITE richiedono un file esistente; CREATE_NEW fallisce se esiste; CREATE_TRUNCATE crea o tronca. READ permette soltanto lettura; READ_WRITE, CREATE_NEW e CREATE_TRUNCATE garantiscono sia lettura sia scrittura. Se il profilo non supporta l'apertura combinata, FILE_OPEN restituisce ENOTSUP prima di creare o troncare: nessuna riduzione implicita dei permessi del modo richiesto.

Ogni read/write può restituire un conteggio inferiore alla richiesta. Per la prima implementazione trasferisce al massimo un blocco dati, inizialmente 128 byte: il programma o un helper bytecode ripete la chiamata. Non allocare un buffer locale della dimensione richiesta dall'app. Una richiesta vuota ritorna zero e non dereferenzia il puntatore, ma verifica comunque l'handle.

`fs.seek` non estende il file: accetta soltanto posizioni fra zero e la dimensione nota verificata, estremi inclusi; oltre EOF restituisce ERANGE senza cambiare cursore o file. Una scrittura può estendere sequenzialmente il file. Prima di inviare ogni singolo blocco calcolare `position + chunk_length` con controllo del riporto: se supera `$FFFFFFFF`, restituire ERANGE con conteggio zero e nessun effetto di quel blocco, senza troncare il trasferimento per farlo entrare. I blocchi completati da chiamate precedenti restano validi.

Directory e metadati fanno parte dell'MVP; file picker completo, cancellazione di directory, copie native di interi alberi e mount restano successivi. Una libreria `read_exact`/`write_all` può essere scritta in C-Script usando slice e loop, quindi resta soggetta al fuel.

`fs.next` richiede un buffer nome di almeno 256 byte, riutilizzato a ogni chiamata. Il wrapper verifica la lunghezza u32 della vista e passa capacità 256 alla syscall, anche per viste più grandi, senza troncare la lunghezza a u16. Scrive `info.name_len` byte e un NUL aggiuntivo; usare `text.view(name, dword(info.name_len))` per il testo. A fine elenco restituisce un record zero e non modifica il buffer. Un buffer insufficiente dà ERANGE senza avanzare il cursore.

I nomi vengono restituiti per intero fino a 255 byte; una voce che non può essere indirizzata dall'API dei path a 127 byte, o contiene byte non ASCII, ha il flag NAME_UNADDRESSABLE. L'interfaccia può mostrarla ma non deve aprirla usando un nome troncato. Nomi oltre 255 byte causano EOVERFLOW dell'apertura, senza pubblicare un elenco incompleto.

### 2.4 SID

| Firma | Comportamento |
|---|---|
| `sid.count() -> word` | SID logici configurati e disponibili |
| `sid.open(index: word) -> (SID, word)` | Lease esclusivo di un intero SID |
| `sid.close(chip: SID) -> word` | Spegne e rilascia il chip |
| `sid.write(chip: SID, reg: byte, value: byte) -> word` | Scrittura controllata di un registro |
| `sid.write_batch(chip: SID, pairs: bytes) -> word` | Coppie registro/valore, da 1 a 25 |
| `sid.note(chip: SID, voice: byte, note: byte, wave: byte, volume: byte) -> word` | Helper semplice, note MIDI 0…95 e voce 0…2 |
| `sid.off(chip: SID, voice: byte) -> word` | Abbassa il gate della voce |

`sid.note` è libreria bytecode con tabella di frequenze PAL generata sul computer di sviluppo, non un nuovo sintetizzatore nativo. Configura frequenza, pulse width iniziale $0800, AD=$09, SR=$F0, gate e volume globale. Wave ammessi: TRIANGLE=$10, SAW=$20, PULSE=$40, NOISE=$80; volume 0…15. Per combinazioni e ADSR personalizzati usare write_batch.

Il lease è per chip, perché filtro e volume sono condivisi fra le sue tre voci. Non promettere isolamento assegnando semplicemente voci diverse a processi diversi. Modello, base e numero dei SID dipendono dal profilo hardware; non hardcodare nel linguaggio il numero massimo teorico del dispositivo.

### 2.5 Ultimate Audio

| Firma | Comportamento |
|---|---|
| `audio.count() -> word` | Canali PCM disponibili nel profilo |
| `audio.open() -> (PCM, word)` | Primo canale libero |
| `audio.play(ch: PCM, sample: bytes, hz: word, volume: byte, pan: byte, loop: bool) -> word` | Avvia PCM signed 8 bit, intero campione; loop opzionale |
| `audio.stop(ch: PCM) -> word` | Ferma la lettura hardware e rilascia il vincolo sul campione |
| `audio.volume(ch: PCM, value: byte) -> word` | Volume 0…63 |
| `audio.pan(ch: PCM, value: byte) -> word` | 0…255, centro iniziale 128 |
| `audio.state(ch: PCM) -> (word, word)` | 0 fermo / 1 in riproduzione, errore |
| `audio.close(ch: PCM) -> word` | Stop e rilascio del canale |

PCM signed 8 bit è il formato logico C-OS. Il driver deve qualificare encoding, rate, loop e pan sul backend: eventuali conversioni vanno dichiarate, non lasciare ambigua la semantica dei campioni. In 0.1 non includere decoder compressi, mixing software o streaming con callback in interrupt.

`hz` inizialmente 1.000…32.000; il driver restituisce ERANGE fuori intervallo. La frequenza effettiva dipende dal divisore hardware e viene riportata nei test. Il formato sorgente non espone il divisore. Campioni non vuoti, interamente nell'arena del proprietario e con lunghezza ≤$FFFFFF.

`loop=true` ripete tutto il campione. Loop con punti A/B, rate variabile e doppio buffer sono estensioni successive; mantenere la prima API piccola.

### 2.6 Informazioni Ultimate

| Firma | Comportamento |
|---|---|
| `ultimate.info() -> (UltimateInfo, word)` | Profilo, versione ABI, capacità e numero di dispositivi |
| `ultimate.has(capability: word) -> bool` | Capacità del profilo, senza nuova probe distruttiva |

Capacità numerate: FILE_IO=0, FILE_SEEK=1, SID=2, PCM8=3, VIDEO_BLIT8=4, RTC=5, FILE_META=6, DIRECTORY=7, FILE_MUTATE=8, STORAGE_ENUM=9. Riservate alle estensioni: TCP_CLIENT=10, UDP_CLIENT=11, HTTP=12, HTTP_JSON=13, HTTPS=14; restano zero nell'MVP. `has(n)` legge il bit n di UltimateInfo; indici sconosciuti sono false. UltimateInfo è l'unica sorgente ABI delle capability; SYS_INFO.R4 resta zero riservato.

Una capability indica un servizio implementato e qualificato sul profilo; non garantisce che un supporto sia inserito o che un dato sia fresco. Le API restituiscono disponibilità ed errori operativi. RTC viene implementato tramite il comando DOS descritto sotto; il widget usa uptime se l'ora non è disponibile. Niente pass-through generale `ultimate.command(raw_bytes)`: le funzioni future avranno servizi tipizzati, con controllo di risorse e durata.

### 2.7 Storage

| Firma | Comportamento |
|---|---|
| `storage.scan() -> (word, dword, word)` | Numero dei supporti, generazione dell'elenco, errore |
| `storage.info(index: word, generation: dword) -> (StorageInfo, word)` | Legge una voce dell'elenco; generazione superata = ESTALE |

Enumerazione iniziale di massimo cinque supporti. Non ritornare un numero parziale come se l'elenco fosse completo: superato il limite, EOVERFLOW. Scansione esplicita, al boot o su richiesta di aggiornamento; nessuna scansione a ogni frame. Richieste concorrenti possono condividere la scansione in corso. Un elenco precedente resta valido fino alla pubblicazione completa di quello nuovo; l'errore di scansione non pubblica una tabella parziale.

StorageInfo descrive tipo SD/USB/altro, unità, presenza osservata, selezione per C-OS e stato read-only se noto. Non promette capacità o spazio libero quando il backend non li fornisce. L'ID è un identificatore diagnostico e non concede accesso a un volume: le normali API `fs` operano sempre nella root assegnata all'app.

### 2.8 Orologio

| Firma | Comportamento |
|---|---|
| `clock.now() -> (DateTime, word)` | Ultimo campione recente dell'RTC; EAGAIN se il refresh è pendente |

Data/ora civile in un record fisso. Il kernel aggiorna una cache condivisa al massimo una volta ogni 50 frame, in un lavoro UCI a bassa priorità. Le chiamate delle app leggono la cache; non moltiplicano le richieste firmware. Un campione più vecchio di 100 frame non viene presentato come attuale: restituire EAGAIN e richiedere un refresh. Senza dispositivo ENODEV; risposta malformata EIO. In caso di EAGAIN/errore il wrapper restituisce un record zero.

Il record riporta il frame in cui è stato acquisito e se l'offset UTC è noto. Senza informazione di fuso orario, zero nell'offset non significa UTC. `system.frame()` rimane il riferimento monotono per timeout e scheduling anche se l'RTC cambia. Impostazione dell'ora e sincronizzazione NTP sono servizi amministrativi successivi.

## 3 ABI dei servizi aggiunti

R0 è sempre lo stato al ritorno. Salvo eccezioni esplicite, output su errore azzerati, nessuna modifica al buffer destinazione. Le syscall core restano definite in SPEC.md.

| ID | Servizio | Input | Output |
|---|---|---|---|
| 20 | FILE_OPEN | P0=path, R1=lunghezza 1…127, R2=mode | R1=File |
| 21 | FILE_CLOSE | R0=File | Stato |
| 22 | FILE_READ | R0=File, P0=dst, R1/R2=lunghezza u32 | R1/R2=byte letti |
| 23 | FILE_WRITE | R0=File, P0=src, R1/R2=lunghezza u32 | R1/R2=byte confermati |
| 24 | FILE_SEEK | R0=File, R1/R2=posizione u32 | Stato |
| 25 | FILE_TELL | R0=File | R1/R2=posizione |
| 26 | FILE_SIZE | R0=File | R1/R2=dimensione |
| 27 | FILE_STAT | P0=path, R1=lunghezza, P1=FileInfo destinazione | Stato |
| 28 | DIR_OPEN | P0=path, R1=lunghezza | R1=Dir |
| 29 | DIR_NEXT | R0=Dir, P0=nome, R1=capacità ≥256, P1=FileInfo destinazione | R1=1 voce / 0 fine elenco |
| 2A | DIR_CLOSE | R0=Dir | Stato |
| 2B | FILE_MKDIR | P0=path, R1=lunghezza | Stato |
| 2C | FILE_RENAME | P0=vecchio path, R1=lunghezza, P1=nuovo path, R2=lunghezza | Stato |
| 2D | FILE_REMOVE | P0=path, R1=lunghezza | Stato |
| 40 | SID_OPEN | R1=indice logico | R1=SID |
| 41 | SID_CLOSE | R0=SID | Stato |
| 42 | SID_WRITE_BATCH | R0=SID, P0=coppie, R1=numero coppie 1…25 | Stato |
| 43 | SID_GATE_OFF | R0=SID, R1=voce 0…2 | Stato |
| 50 | AUDIO_OPEN | — | R1=PCM |
| 51 | AUDIO_CLOSE | R0=PCM | Stato |
| 52 | AUDIO_PLAY | R0=PCM, P0=AudioDesc | Stato |
| 53 | AUDIO_STOP | R0=PCM | Stato |
| 54 | AUDIO_VOLUME | R0=PCM, R1=volume | Stato |
| 55 | AUDIO_PAN | R0=PCM, R1=pan | Stato |
| 56 | AUDIO_STATE | R0=PCM | R1=0/1 |
| 60 | VIDEO_INFO | P0=VideoInfo destinazione, 16 byte | Stato |
| 61 | VIDEO_CLIENT_SIZE | R0=Window | R1=larghezza, R2=altezza |
| 70 | ULTIMATE_INFO | P0=UltimateInfo destinazione, 16 byte | Stato |
| 71 | CLOCK_NOW | P0=DateTime destinazione, 16 byte | Stato |
| 72 | STORAGE_SCAN | — | R1=numero, R2/R3=generazione low16/high16 |
| 73 | STORAGE_INFO | R1=indice, R2/R3=generazione, P0=StorageInfo destinazione | Stato |

Ogni coppia R1/R2 u32 è low16/high16; STORAGE usa esplicitamente R2/R3. Oltre alle syscall core, l'ID 30 NUM_OP è definito in [NUMERICS.md](NUMERICS.md); non usa UCI e non è una capability hardware. Gli ID non definiti da alcun allegato o dalla specifica core sono ENOSYS; 80–8F sono riservati alla futura rete e 90–9F al futuro HTTP, senza handler nell'MVP.

AudioDesc, 16 byte: puntatore sample u24 a 0; flag a 3 (bit0 loop); lunghezza u32 a 4; hz u16 a 8; volume u8 a 10; pan u8 a 11; quattro byte zero a 12. Requisiti e check vengono applicati all'intera sorgente, non solo al primo blocco cache.

VideoInfo, 16 byte: ABI u16 a 0; width/height u16 a 2/4; formati u16 a 6 (bit0 BLIT4, bit1 BLIT8); numero colori u16 a 8 (=16); flag u16 a 10 (bit0 mapping diretto, sempre zero nella 0.1); quattro byte zero a 12. Nessun indirizzo o formato UPIC.

UltimateInfo, 16 byte: ABI u16 a 0; capability bits u32 a 2; sid_count u8 a 6; pcm_count u8 a 7; timing_profile_id u16 a 8; hardware_profile_id u16 a 10; firmware_profile_id u16 a 12; due byte zero a 14. Gli ID del profilo sono chiavi del manifest/report, non interpretazioni arbitrarie della stringa di versione firmware.

Handle di ogni tipo: un contatore monotono u16 per incarnazione del processo, condiviso fra Window/File/Dir/SID/PCM; la shell ha un proprio contatore. Zero è invalido e nessun ID viene riutilizzato nella stessa incarnazione. Ogni lookup usa identità del processo chiamante, incarnazione, ID, tipo e stato vivo: lo stesso valore numerico in due app non identifica la stessa risorsa. I record del kernel verificano sempre proprietario e tipo, anche per bytecode scritto a mano.

Ogni incarnazione ammette quindi al massimo 65.535 creazioni di handle. All'esaurimento le sue nuove aperture restituiscono ENOSPC senza consumare gli ID di altre app o della shell; le risorse già aperte continuano a funzionare. Il contatore dell'app riparte soltanto dopo terminazione, cleanup completo e nuova partenza con contesto e dati inizializzati ripristinati. Le continuazioni della vecchia incarnazione non possono consegnare risultati a quella nuova. Il contatore della shell dura per la sessione del sistema; anche il suo esaurimento fallisce senza wrap.

### 3.1 Record di file, directory, storage e ora

DateTime, 16 byte:

| Offset | Campo |
|---|---|
| 0 | `year`, u16, 1…9999 |
| 2 | `month`, u8, 1…12 |
| 3 | `day`, u8, valido per mese/anno |
| 4 | `hour`, u8, 0…23 |
| 5 | `minute`, u8, 0…59 |
| 6 | `second`, u8, 0…59 |
| 7 | `flags`, u8: bit0 VALID, bit1 OFFSET_KNOWN |
| 8 | `utc_offset_minutes`, i16; zero se sconosciuto |
| 10 | Due byte riservati zero |
| 12 | `sampled_frame`, u32; zero quando il record rappresenta il timestamp di un file |

FileInfo, 32 byte: `kind` u8 a 0 (0 sconosciuto, 1 file, 2 directory, 3 altro); `attributes` u8 a 1 (READ_ONLY=1, HIDDEN=2, SYSTEM=4, ARCHIVE=8); `valid` u16 a 2 (SIZE=1, MODIFIED=2); `size` u32 a 4; `modified` DateTime a 8; `name_len` u16 a 24; `flags` u16 a 26 (NAME_UNADDRESSABLE=1); quattro byte zero a 28. Campi senza bit di validità sono zero e non vanno interpretati come misure reali. Per `stat`, name_len è la lunghezza del componente finale, zero per la root `"."`.

`fs.FILE=1`, `fs.DIRECTORY=2`, `fs.SIZE_VALID=1`, `fs.MODIFIED_VALID=2` e `fs.NAME_UNADDRESSABLE=1` sono costanti SDK. Un elenco directory non esegue automaticamente stat per ogni voce: normalmente contiene tipo, attributi e nome; dimensione/data possono restare sconosciute. Richiedere stat quando servono, ad esempio sulla voce selezionata.

StorageInfo, 16 byte: `id` u16 a 0; `kind` u8 a 2 (1 SD, 2 USB, 3 altro); `unit` u8 a 3; `flags` u16 a 4 (PRESENT=1, SELECTED=2, READ_ONLY=4, READY=8, READ_ONLY_KNOWN=16); due byte zero a 6; `generation` u32 a 8; quattro byte zero a 12. READY indica che il supporto è stato accessibile durante la scansione, non che qualunque operazione futura avrà successo. Gli ID possono essere riutilizzati soltanto con una nuova generazione della tabella.

I record restituiti dal wrapper sono valori copiati nel frame del chiamante; non contengono puntatori a scratch del kernel. DIR_NEXT valida tutti gli output, inclusa l'assenza di sovrapposizione fra nome e FileInfo, prima di copiare e avanzare. Anche a fine elenco scrive FileInfo zero. Su errore gli output in memoria restano invariati; il wrapper azzera i propri risultati, come per le altre syscall.

## 4 Driver UCI incrementale

UCI è una risorsa condivisa; il kernel possiede l'interfaccia per l'intera sessione. Le librerie esistenti sono riferimenti del protocollo, non da importare con i loro busy wait. La documentazione descrive FIFO, stato/ack e comandi DOS; alcune funzioni sono marcate non testate. Verificare protocollo e firmware alla revisione usata dal progetto. [Manuale della libreria UCI](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md), [interfaccia DOS](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.h).

Macchina a stati minima:

```text
IDLE -> PREPARE -> SEND_CHUNK -> PUSH -> WAIT_RESPONSE
                                  -> DRAIN_DATA -> DRAIN_STATUS -> ACK
                                  -> COMPLETE / NEXT_STEP
qualsiasi stato -> TIMEOUT -> ABORT/DRAIN -> RECOVER oppure OFFLINE
```

Ogni visita esegue al massimo un numero fisso di accessi FIFO o un breve polling, inizialmente ≤32 byte o un singolo controllo stato. Il limite effettivo deve passare la verifica temporale, non essere solo un limite in byte. PREPARE può richiedere cache/DMA e deve poter sospendere senza mutare i registri di una transazione già attiva.

L'arbitro serializza i comandi fino alla risposta completa, status incluso. Nessun secondo processo può consumare dati/status della richiesta precedente. Non fare read-modify-write su registri di controllo che condividono l'indirizzo con uno stato di lettura: usare valori di comando espliciti.

Non tenere gli interrupt disabilitati durante l'attesa di USB/SD/firmware. Il raster mantiene priorità; in v0.1 anche il servizio UCI viene eseguito fuori dalle 200 righe attive. Il backend deve verificare che pause fra pezzi di FIFO siano ammesse.

Timeout iniziale: 250 frame PAL per una transazione di comando, configurabile per profilo; usare differenze del contatore frame con wrap corretto. La UI deve restare reattiva anche se l'app aspetta cinque secondi. Un timeout non autorizza a ripetere una scrittura: l'esito esterno potrebbe essere incerto.

Una recovery limitata invia abort/draina secondo protocollo. Se non raggiunge uno stato noto entro un secondo limite configurato, marca il backend OFFLINE, fallisce le richieste pendenti e lascia funzionare desktop/VM/video. Non fare un reset generale dell'Ultimate per recuperare una syscall.

I comandi firmware che scrivono direttamente nella RAM C64/REU o caricano intere immagini non sono il percorso iniziale del servizio file. Prima di usarli occorre dimostrare controllo degli intervalli, coerenza e interferenza temporale accettabile. Il percorso baseline passa per FIFO e copie REU limitate del kernel.

## 5 File handle, path e concorrenza

Il protocollo DOS di riferimento espone il file correntemente aperto e una directory corrente. Non trattarlo come una tabella di file descriptor indipendenti. I file logici di C-OS sono virtualizzati sopra questo stato. [Dichiarazioni delle operazioni DOS](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.h).

Limiti iniziali: quattro handle file userspace globali, massimo due per app, più un handle riservato alla shell. Metadati freddi e path in REU; mantenere in RAM locale soltanto il contesto della transazione attiva e gli indici necessari. Il kernel non riserva 128 byte locali per ogni path.

Per ogni handle conservare proprietario/generazione, path canonico, modo, posizione u32, stato e dimensione nota. Prima di servire un handle diverso da quello aperto fisicamente:

1. Terminare la transazione precedente e chiudere il file fisico se necessario.
2. Selezionare la directory/il path corretti senza esporre un cwd condiviso all'app.
3. Riaprire in modalità non distruttiva: CREATE/TRUNCATE avvengono **soltanto** alla prima FILE_OPEN logica.
4. Ripristinare la posizione con seek verificato.
5. Eseguire il singolo read/write, aggiornare la posizione soltanto in base ai byte confermati.

Mantenere il file fisico aperto è una piccola ottimizzazione quando il proprietario non cambia. Round-robin fra richieste complete a blocchi, senza assegnare il backend a un'app per tutta la vita del suo handle.

Seek e riapertura senza troncamento sono test obbligatori della milestone file. Se un firmware non li supporta correttamente, riportare la limitazione del profilo: non dichiarare completata la concorrenza I/O e non simulare handle indipendenti sopra un solo cursore fisico.

L'installazione iniziale produce un albero dati da copiare sullo storage: `cos/apps/<id>` per ogni ID stabile e `cos/.system` per la shell. La root fisica viene scoperta o selezionata secondo la sezione 5.4; il sorgente usa nomi relativi come `notes.txt`, non `/usb0/...`.

Path ASCII da 1 a 127 byte, relativi, senza NUL, componenti `..`, backslash o prefissi assoluti; normalizzare separatori e `.` prima del controllo della root. Una directory mancante restituisce ENOENT. `"."` identifica la root per stat/opendir; le mutazioni della root sono vietate. Nessun cambio globale di cwd da parte dell'app. `mkdir` crea soltanto la directory esplicitamente richiesta entro questa root.

Il kernel serializza accessi al medesimo path: più lettori sono ammessi; uno scrittore esclude altri handle sullo stesso file finché resta aperto. Conflitto = EBUSY. Questo protegge le app C-OS tra loro, non le modifiche fatte fuori da C-OS dal menu firmware o da un altro computer.

READ può lasciare un prefisso valido nel buffer e restituire `count>0` con errore; WRITE restituisce soltanto byte confermati dal firmware. È un'eccezione esplicita alla regola output-zero su errore. Un successo WRITE con `count>0` conferma esattamente quel prefisso e avanza di count; non promette la scrittura dell'intera vista richiesta. Se il backend non conferma il conteggio parziale dopo un errore, il kernel non lo deduce dalla lunghezza inviata: count resta zero per il blocco incerto, anche se il dispositivo potrebbe averne scritto una parte. Timeout/reset o errore con avanzamento non determinabile invalidano l'handle e richiedono una riapertura esplicita. Non ritentare automaticamente la porzione incerta; un errore con count zero non dimostra che il file sia rimasto intatto.

FILE_CLOSE invalida l'handle anche in caso di errore del backend. Il successo significa completamento del comando di chiusura, non una garanzia fisica di durata oltre quelle dello storage. La terminazione del processo non deve inviare ulteriori dati dell'app dopo il suo kill; completa soltanto protocollo e cleanup necessari.

### 5.1 Persistenza del desktop

Due slot `layout.0` e `layout.1` nella directory `.system`. Ogni salvataggio scrive lo slot meno recente, lasciando quello valido corrente intatto. Non dipende da rename atomico o da nuove funzioni filesystem.

Formato: header 16 byte e N record da 8 byte, N≤12, lunghezza totale esatta `16+8*N`:

| Offset header | Campo |
|---|---|
| 0 | Quattro byte ASCII `COSL` |
| 4 | Versione u16 = 1 |
| 6 | N, u8 |
| 7 | Riservato zero |
| 8 | Generazione u32 |
| 12 | CRC16 u16 |
| 14 | Due byte zero |

Record: ID oggetto u16 a 0; tipo u8 a 2 (1 launcher, 2 widget); colonna u8 a 3; riga u8 a 4; flag u8 a 5 (zero inizialmente); due byte zero a 6. CRC16-CCITT-FALSE, polinomio $1021, init $FFFF, senza riflessione/xor finale; calcolato su tutto il file trattando i due byte CRC come zero.

Al boot scegliere lo slot valido più recente con confronto modulo 2^32 a distanza <2^31. A parità preferire slot 0; casi ambigui o file entrambi invalidi usano il default. ID sconosciuti, duplicati, coordinate fuori griglia o collisioni rendono lo slot invalido nella 0.1.

Dopo la scrittura e la chiusura, rileggere e validare prima di considerare completato il salvataggio. Se lo storage scompare, tenere il layout in RAM e riportare l'errore. Debounce di 50 frame dall'ultimo movimento; una nuova modifica durante il salvataggio marca un altro salvataggio pendente senza alterare il buffer già inviato.

### 5.2 Elenchi directory in REU

Il protocollo di riferimento restituisce una sequenza di pacchetti con attributi e nome. Il kernel deve completare o annullare questo comando prima di usare UCI per altri comandi; lasciare una directory aperta in attesa della prossima chiamata dell'app bloccherebbe gli altri servizi. [Implementazione DOS: directory e stat](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.c).

DIR_OPEN raccoglie l'elenco in una snapshot privata del kernel nella REU, procedendo per pezzi limitati. Quando la risposta e lo status sono stati consumati, pubblica l'handle Dir e rilascia UCI. DIR_NEXT legge soltanto la snapshot; un'app che non la scorre non trattiene il canale firmware.

Limiti iniziali: due snapshot globali, al massimo una per processo, ciascuna da 16 KiB, fino a 256 voci e nomi di massimo 255 byte. Il limite in byte può essere raggiunto prima del numero di voci. I 32 KiB provengono dalla riserva sistema già prevista, agli indirizzi indicati in SPEC.md; non sono RAM locale aggiuntiva.

Formato interno semplice: header compatto, poi record FileInfo da 32 byte seguiti da name_len byte di nome e padding zero fino a un offset pari. Il cursore conserva offset e indice della prossima voce. Nessuna tabella di puntatori userspace, allocazione per voce o ordinamento nel driver. La snapshot non è direttamente mappata all'app.

DIR_OPEN pubblica soltanto elenchi completi. Directory vuota = successo e prima DIR_NEXT con bool=false. Superamento di un limite = EOVERFLOW, handle zero, snapshot liberata e comando drenato/annullato prima di un'altra operazione. Non consumare lo spazio destinato alla seconda snapshot. Se non c'è uno slot libero restituire ENOSPC; se l'app possiede già un Dir, EBUSY.

La raccolta rispetta il timeout e le regole di abort del motore UCI. Durante la raccolta progrediscono VM, input e video; altri comandi UCI attendono la fine della transazione. Il limite della directory è visibile nella diagnostica e nel messaggio della demo. Aumentarlo è un parametro da misurare, non un motivo per restituire silenziosamente le prime voci come elenco completo.

Saltare le voci sintetiche `.` e `..`. Convertire gli attributi nel formato SDK; preservare il nome esatto. FileInfo.valid non deve marcare size o modified quando il pacchetto non li contiene. Stat separato converte il formato del timestamp restituito dal firmware, senza inventare un fuso orario.

L'elenco è una fotografia della scansione: dopo rename/create/remove, l'app lo riapre per aggiornarlo. Una vecchia snapshot può ancora contenere nomi non esistenti; questo non impedisce le mutazioni. Non garantire una fotografia atomica rispetto a modifiche esterne al sistema. Rimozione del supporto rilevata o cambio della root invalida invece gli handle legati a quella sessione di storage.

### 5.3 Mutazioni piccole e delimitate

Mkdir, rename e remove fanno parte del primo servizio file. Validare tutti i path e riservare la transazione prima degli effetti. Su un supporto noto read-only restituire EROFS; non provare scritture per scoprirne lo stato durante una scansione.

- Mkdir crea una sola directory, con antenati già presenti. Destinazione esistente = EEXIST.
- Rename opera nella stessa root, senza rimpiazzare una destinazione esistente. Entrambi i nomi sono validati prima dell'invio; vietati root, spostamento di una directory dentro sé stessa e attraversamento di supporti.
- Remove elimina un solo file. Le directory restituiscono EISDIR; nessuna cancellazione ricorsiva o espansione di wildcard.
- File aperti coinvolti, o file aperti sotto una directory che si vuole rinominare, causano EBUSY. Una snapshot di elenco non è un file aperto e non impedisce le modifiche.
- Il driver non ritenta automaticamente una mutazione dopo un timeout dall'esito incerto. Restituisce l'errore e richiede alla logica chiamante di rileggere lo stato.

Confronti e lock dei path devono rispettare anche alias di maiuscole/minuscole del backend. Per i nomi ASCII su storage FAT, due varianti di case non possono aggirare il lease di un file. Conservare il nome originale per la visualizzazione e una chiave canonica per i lock. Il profilo deve verificare la semantica di rename senza overwrite, non dedurla dal nome del comando.

Un salvataggio in file temporaneo può usare queste primitive, ma l'SDK non promette sostituzione atomica o durata su disco. Il layout della shell mantiene il formato a due slot della sezione 5.1.

### 5.4 Scoperta e ciclo di vita dello storage

Usare l'enumerazione delle root visibili al firmware per scoprire USB/SD, invece di assumere la presenza di `/usb0/`. Il riferimento esistente effettua questa scansione con le operazioni directory; non è un nuovo dispositivo hardware. Il driver C-OS deve farlo tramite il motore UCI incrementale. [Helper di scansione media](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.c).

La scansione di sistema filtra il flusso delle directory direttamente nella piccola tabella dei supporti. Conserva in REU al massimo cinque path radice di supporto, ciascuno in 128 byte incluso il terminatore; i suffissi C-OS sono costruiti separatamente. Non richiede un terzo buffer da 16 KiB e deve poter procedere anche quando entrambe le snapshot delle app sono occupate. Candidati o path oltre i limiti causano EOVERFLOW, senza troncamenti o pubblicazione parziale.

In modalità discover del manifest, cercare la directory `cos` e il file marker `.cos-volume`, prodotto dagli strumenti di installazione con contenuto ASCII esatto `COSDATA1\n`. La scansione legge soltanto. Un solo candidato valido diventa la root del sistema; più candidati richiedono una scelta nella shell, oppure un path esplicito nel manifest. In assenza di una root selezionata il desktop funziona in RAM, e le API file restituiscono ENODEV.

Il marker serve a riconoscere una directory predisposta, non a identificare univocamente un supporto fisico. Scelta del volume e creazione iniziale dell'albero dati appartengono alla shell/agli strumenti di installazione; `storage.scan` eseguito da un'app non cambia la root attiva e non scrive su alcun volume.

Pubblicare l'elenco con una generazione u32. Se i dati osservati sono identici, la generazione può restare uguale; se cambiano, incrementarla e rifiutare le vecchie coppie indice/generazione con ESTALE. Non avvolgere il contatore: all'esaurimento restituire EOVERFLOW. Un errore di nuova scansione non significa che il vecchio elenco sia una fotografia aggiornata.

Separare questa generazione dalla sessione del supporto usata dagli handle file/Dir. Una scansione senza cambiamenti non deve invalidare file aperti. Una rimozione rilevata, un cambio della root o una recovery che perde il contesto dei file chiudono la sessione: vecchi handle danno ESTALE finché identificabili come revocati, oppure EBADF dopo cleanup. I nuovi handle hanno nuovi ID.

Dopo una perdita del supporto, non selezionare automaticamente un altro candidato e non riprendere scritture pendenti su di esso. La shell può riconnettere/selezionare il volume; le app devono riaprire esplicitamente i file e gestire gli errori già ricevuti. Non promettere rilevamento istantaneo di un cambio fisico avvenuto interamente fra due osservazioni: qualificare ciò che il firmware consente di rilevare.

Prima di directory, stat o scansioni che cambiano il cwd del firmware, preservare i cursori logici e chiudere/invalidare il binding del file fisico quando necessario. L'operazione successiva di un'app deve comunque riaprire il proprio path corretto e ripristinare il proprio offset.

### 5.5 Lettura RTC

Il backend usa DOS GET_TIME `$26`, sul target DOS; la libreria di riferimento legge una stringa `yyyy/mm/dd hh:mm:ss`. Non usare il distinto opcode RTC del target Control, indicato come non implementato nella documentazione della libreria. [Implementazione time](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_time_lib.c), [tabella dei comandi UCI](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md).

Validare lunghezza, cifre, separatori e data di calendario prima di pubblicare DateTime. Una risposta malformata non sostituisce il campione valido con valori parziali. Il frame di acquisizione viene registrato quando il campione è completo; la cache viene pubblicata tutta insieme.

Iniziare un refresh al boot dopo la disponibilità di UCI. Durante il funzionamento, tenere al massimo un refresh pendente e servire il clock a bassa priorità. Risposta non supportata = capability RTC disattivata per il profilo; indisponibilità temporanea o dato vecchio = errore operativo, senza alterare il contatore monotono. Una lettura valida non certifica che l'orologio sia sincronizzato o impostato correttamente dall'utente.

Il widget distingue ora civile e uptime. Non scrivere nell'RTC per ottenere una lettura e non impostare la data da quella della build.

## 6 Driver SID

La tabella dei SID logici viene dal profilo verificato: base I/O, modello/frequenza e disponibilità. Vietare intervalli che si sovrappongano a REU, UCI, sampler o altri dispositivi attivi. L'assenza di un chip leggibile non può essere diagnosticata con un semplice read-back di registri write-only.

Scritture ammesse ai registri $00…$18 del SID selezionato, al massimo 25 coppie. Il kernel mantiene lo shadow dei control register per gate-off e cleanup; non leggere un registro di scrittura per ricostruirne il valore.

Validare tutte le coppie prima della prima scrittura. La durata massima di 25 scritture va misurata; se il batch non entra nel tempo disponibile, rimandarlo intero. Non presentare il batch come atomico rispetto all'elettronica analogica: le scritture arrivano nell'ordine indicato.

All'apertura impostare uno stato silenzioso noto. Alla chiusura/kill abbassare i gate, azzerare il volume e rilasciare il lease nella prima finestra temporale sicura. Un'app proprietaria del chip controlla anche filtro e volume; le altre ottengono EBUSY. Nessuna callback userspace da IRQ audio.

Esempio C-Script:

```text
import sid
import system

fn main() {
    let chip, err = sid.open(0)
    if err != 0 { return }
    sid.note(chip, 0, 60, sid.TRIANGLE, 10)
    system.sleep(20)
    sid.off(chip, 0)
    sid.close(chip)
}
```

## 7 Driver Ultimate Audio e campioni in REU

L'interfaccia di riferimento descrive sette canali, campioni a 8 bit, volume massimo 63 e registri per indirizzo, lunghezza e rate. Il codice converte gli offset REU in indirizzi SDRAM e scrive alcuni campi in ordine big endian. Questi dettagli restano nel driver, non nell'ABI guest. [Header audio](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.h), [implementazione audio](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.c).

Il profilo deve fissare registro per registro formato, segni, bit di loop/start/stop, ordine delle scritture e divisore. La routine di detect del riferimento modifica lo stato dei canali: eseguirla eventualmente al boot prima di assegnare risorse, mai come risposta a `audio.count()` durante una riproduzione. Non copiare commenti contraddittori sui bit o sull'endianness senza verificare il codice e l'uscita.

Esiste già un riferimento locale per PCM signed e divisori in `tools/generate_e1m1_audio.py` nel workspace C64 originale, esterno a questa repository, con conversione unsigned→signed e gestione del campione finale. Esaminarlo senza modificarlo; documentare la formula realmente qualificata nel profilo C-OS, poiché i riferimenti non usano tutti la stessa approssimazione del rate. STOP/CLOSE/cleanup devono portare anche il volume a zero, evitando di scambiare la fine delle letture per la garanzia di silenzio in uscita. Testare esplicitamente il mantenimento dell'ultimo campione e il completamento one-shot.

Il kernel traduce l'offset guest in un indirizzo hardware consentito; non permette a un descrittore dell'app di selezionare un'altra banca SDRAM. Un PLAY non può far leggere al dispositivo dati del kernel o di altre app.

### 7.1 Proprietà, coerenza e protezione

Per evitare una seconda copia di ogni campione, PLAY legge direttamente il campione già nella REU dell'app. La regione viene **protetta dalle scritture per tutta la durata della riproduzione**:

1. Validare l'intero intervallo e il lease del canale. Per sostituire un campione, validare il nuovo prima di fermare quello vecchio, quando possibile.
2. Completare i write-back delle linee dirty interessate; invalidare eventuali permessi di scrittura memorizzati nei metadati della cache.
3. Registrare il vincolo read-only, poi programmare il canale in una finestra sicura. Pubblicare PLAYING soltanto dopo l'avvio riuscito.
4. LOAD, blit e FILE_WRITE con il campione come sorgente restano consentiti. STORE VM verso il campione genera fault `READ_ONLY`; MEM_FILL/MEM_COPY/FILE_READ con destinazione sovrapposta restituiscono EBUSY prima degli effetti.
5. STOP/CLOSE/kill fermano l'hardware prima di rilasciare il vincolo. Il completamento one-shot viene rilevato con polling limitato; solo dopo viene sbloccata la regione.

Più canali possono leggere intervalli sovrapposti dello stesso processo; una regione resta protetta finché almeno un canale la usa. Massimo sette record di vincolo, associati ai canali, senza allocatore generale nel kernel.

Il percorso STORE senza campioni attivi deve rimanere economico: flag per processo per saltare il controllo aggiuntivo quando il numero di vincoli è zero. Con audio attivo, il costo massimo del controllo va incluso nei limiti temporali degli opcode; non introdurre un percorso che ignori il vincolo su un cache hit.

Il rilevamento del fine campione non può basarsi solo su una stima `length/hz` se l'hardware può essere rallentato, fermato o in loop. Qualificare la condizione di completamento reale. Se non affidabile, mantenere il vincolo finché STOP esplicito e riportare tale limite del profilo.

Un fault dell'app che scrive nel proprio campione provoca il normale cleanup e non deve lasciare una lettura hardware su memoria poi riutilizzata. Nessun ring buffer modificabile contemporaneamente nella prima API.

### 7.2 Timing

Il sampler legge memoria indipendentemente dal codice VM: verificarne l'interferenza con DMA REU e scanout, senza dedurre assenza di costo dal fatto che non esegue opcode. Il profilo iniziale può pubblicare meno di sette canali se è l'unico numero qualificato; riportare il limite e la misura.

Disabilitare IRQ sampler non necessari. Tutte le scritture ai registri sono brevi e fuori dal raster attivo nella prima versione. Il driver esegue una sola conversione nativa hz→divisore per PLAY, con costo massimo misurato e durata limitata; AudioDesc trasporta soltanto hz. La conversione fa parte della preparazione del job e non viene ripetuta durante la riproduzione.

Esempio: onda quadra firmata, 64 campioni ripetuti a 8 kHz:

```text
import audio
import system

fn main() {
    let channel, err = audio.open()
    if err != 0 { return }
    let sample = bytes(64)
    for i in 0..sample.len {
        if i < 32 { sample[i] = 48 }
        else { sample[i] = 208 } // byte che rappresenta -48 in PCM signed
    }
    let play_error = audio.play(channel, sample, 8000, 16, 128, true)
    if play_error == 0 { system.sleep(50) }
    audio.stop(channel)
    audio.close(channel)
}
```

Il programma non modifica `sample` durante PLAY. Il suono continua quando la VM cede il turno, perché la riproduzione appartiene all'hardware.

## 8 Dimensioni e implementazione minima

Usare lo staging da 512 byte già previsto dalla mappa; UCI, grafica e DMA lo prenotano esplicitamente, senza mantenere puntatori a uno staging che un altro job può sovrascrivere durante una sospensione. Una richiesta sospesa conserva in REU i dati che non possono restare nello staging prenotato.

Metadati freddi dei file, snapshot directory e profilo stanno nella riserva sistema REU. Le continuazioni attive, i lease audio e i piccoli shadow indispensabili entrano nel budget RAM misurato. Generare il report anche con tutti i driver abilitati: una build con servizi esclusi non dimostra che il sistema completo entri nei 20 KiB. Riportare separatamente i due buffer directory da 16 KiB, i metadati storage e i 16 byte della cache RTC; questi ultimi possono risiedere in REU se il budget locale lo richiede.

Riusare il motore di lavori limitati per conversione pixel, copie, file e flush. Evitare una coda o uno scheduler indipendente per ogni libreria. I wrapper, formattazione del testo, tabelle SID e helper file possono essere bytecode nelle arene delle app.

La prima consegna può implementare servizi per tappe, ma la release MVP deve contenere i binding e i driver richiesti. Hardware assente e hardware non ancora implementato sono due condizioni differenti da rendere esplicite nel rapporto.

## 9 Test obbligatori

1. Valori, handle, proprietari, lunghezze, descrittori e indirizzi malformati; nessuna scrittura fuori arena o I/O non autorizzato.
2. VideoInfo senza mapping; BLIT8 attraversa 64 KiB, coord negative, crop e X dispari; confronto dei pixel attesi.
3. Due app leggono e scrivono file distinti con cursori differenti, alternandosi a ogni blocco; checksum finale e dimensioni corretti.
4. Riapertura di un file CREATE_TRUNCATE durante lo switching senza nuovo troncamento; conflitto sul medesimo path; read+write garantiti dai tre modi scrivibili oppure ENOTSUP prima di creare/troncare.
5. Read/write parziali, EOF, spazio esaurito, storage rimosso, risposta ritardata e timeout; conteggio non inventato su scrittura incerta e nessun busy wait che blocchi il raster. Seek a EOF, oltre EOF e write vicino al limite u32, con ERANGE senza effetti per il blocco che eccede.
6. Kill in ogni stato UCI: nessuna risposta consegnata a un altro processo o file, nessun retry di una scrittura dall'esito incerto.
7. File layout troncato, CRC errato, ID duplicati e collisioni; recupero dello slot valido e default se necessario.
8. SID: lease conteso, batch invalido senza effetti, gate-off/volume zero su kill, shadow coerente.
9. PCM: dati appena scritti in cache, sample oltre 64 KiB, ultimo indirizzo valido, tentativo oltre REU, range non proprio, loop e one-shot.
10. Scritture CPU/native durante pin audio, overlap fra canali e rilascio solo dopo ultimo stop; niente campioni alterati o letture dopo riuso dell'arena.
11. Riscontro dell'audio riprodotto: frequenza/encoding, volume, pan e stop sul backend disponibile; i soli log dei registri non sono una prova del suono.
12. Stress combinato VM/UI/UCI/PCM per dieci minuti con report di latenza, deadline, occupazione RAM, traffico DMA e progressi delle app.
13. Directory vuota, due snapshot contemporanee, limite in byte/voci, nome da 255 byte, nome non indirizzabile, buffer nome corto e kill durante la raccolta; nessun handle parziale e UCI nuovamente disponibile.
14. Elenco directory seguito da I/O su file con posizioni diverse: cwd e cursori non devono contaminarsi. Una snapshot non consumata non impedisce altre operazioni UCI.
15. Stat con data/dimensione note e sconosciute; attributi normalizzati, timestamp valido e nessun fuso inventato. Nuova scansione dopo una modifica aggiorna l'elenco.
16. Mkdir senza antenati, rename con destinazione esistente, lock anche con case diverso, remove di directory, tentativi fuori root e timeout di mutazione senza retry.
17. Nessuno storage, un candidato, più candidati, tabella cambiata, generazione vecchia, limiti superati, scansione con entrambe le snapshot occupate, supporto read-only e scollegamento durante read/write; nessun passaggio automatico a un altro volume.
18. RTC valido, assente, risposta malformata, cache scaduta, cambio all'indietro, attraversamento del wrap di system.frame; tutti i timeout continuano a usare tempo monotono.
19. Handle chiuso passato a wait/input_state dopo close/reopen; nessun evento consumato dalla nuova finestra. Overflow input, INPUT_RESET/BLUR, trascinamento fuori client, Shift rilasciato prima del tasto e comandi globali consumati dalla shell; nessun tasto mantenuto bloccato nell'app.
20. Esaurimento dei 65.535 ID di un'app senza effetti sulle nuove aperture delle altre app o della shell; cleanup e nuova incarnazione, con nessuna continuazione o handle vivo ereditati.

Conservare revisioni delle fonti hardware, versione firmware e impostazioni insieme ai risultati. Le capacità esposte devono corrispondere a ciò che è stato implementato e verificato nel profilo, non all'elenco massimo di funzioni del firmware.

## 10 Estensioni dopo l'MVP

Questa roadmap prepara il seguito senza richiedere nuovi driver residenti nella prima build. Le firme sono proposte per C-Script; record, codici d'errore specifici e assegnazioni degli ID verranno congelati dopo le prove del backend. Importare `net` o `http` nell'MVP deve produrre un errore di compilazione chiaro, senza stub che simulino un successo.

### 10.1 N1: client TCP/UDP

Prime API proposte: `net.connect(host, port, timeout)`, `net.udp(host, port)`, `net.read(socket, dst, timeout)`, `net.write(socket, src, timeout)`, `net.close(socket)` e `net.info()`. Handle Socket del kernel; due socket per app e quattro globali come limiti iniziali da misurare. DNS/connect e trasferimenti devono avere timeout e possibilità di cleanup; i dati sono buffer binari con lunghezza, anche se contengono NUL.

Il firmware espone TCP/UDP client; i vecchi comandi listener non sono da considerare disponibili senza verificare il dispatcher del firmware target. [API di rete e limiti documentati](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md#13-network-functions).

TCP restituisce conteggi parziali, distingue timeout da EOF e conserva i byte accettati su errori parziali. Per UDP definire una API separata di datagrammi se il firmware preserva confini e metadati: non inventare semantica datagramma sopra una semplice sequenza di byte. Qualificare questo punto prima di congelare le firme.

Gate N1: verificare attesa di DNS/connect/read, comportamento di abort e recupero, reale rilascio dei socket su kill e interferenza con file I/O. Un servizio asincrono rispetto alla VM può comunque occupare tutta UCI per secondi: misurare anche il ritardo imposto alle altre richieste, non soltanto la continuità del raster.

Esempi di accettazione: client testuale verso un server locale, trasferimento binario con NUL e timeout; richiesta NTP UDP come demo successiva, senza scrivere automaticamente nell'RTC. Servizi server TCP e configurazione IP globale restano separati.

### 10.2 N2: HTTP e JSON nel firmware

Il target HTTP presente nel sorgente firmware v3.15a gestisce header, body, scambi e strutture JSON; i wrapper di riferimento sono marcati non ancora testati su hardware. [Sorgente firmware HTTP](https://github.com/GideonZ/1541ultimate/blob/v3.15a/software/io/command_interface/http_target.cc), [stato dei wrapper](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_http_lib.h).

API iniziali proposte: `http.get(url, timeout)`, `http.read(response, dst)`, `http.status(response)`, `http.close(response)`. Aggiungere header e POST soltanto dopo il percorso GET binario. Per risposte JSON: `http.json_int(response, path)` e `http.json_text(response, path, dst)`, con output in buffer del chiamante, tipi verificati e nessuna allocazione implicita per campo.

Questo può ridurre il lavoro della VM delegando parsing e gestione HTTP al firmware. Non obbliga C-Script a introdurre oggetti dinamici. Limiti iniziali proposti: una exchange UCI alla volta, una risposta viva per app, lunghezza URL/header e dimensione risposta limitate dal kernel prima e durante il trasferimento.

Il kernel mantiene la proprietà di tutti gli handle header/body firmware, incluse risposte temporanee e percorsi di errore. Una chiamata globale del tipo FREE_ALL non può essere usata per il cleanup di una singola app. Rilasciare soltanto i suoi handle; verificare che timeout/abort non lascino oggetti irraggiungibili nel firmware.

Gate N2: GET testuale/binario e JSON, risposta malformata, body oltre quota, disconnessione, cleanup, latenza degli altri servizi UCI e misure CPU/RAM. Il backend UCI comune è una dipendenza, non la precedente implementazione dei socket N1: se qualificato, HTTP può essere sviluppato senza scrivere lo stack HTTP su TCP nella VM.

HTTPS ha una capability distinta. Abilitarla solo dopo avere verificato supporto effettivo e autenticazione TLS, compresi catena dei certificati e hostname; non accettare URL https declassificandoli a http. Documentare redirect e limiti del firmware prima di esporli come comportamento garantito.

### 10.3 Altre API e responsabilità della shell

Palette programmabile: utile soprattutto con un futuro fullscreen. Il kernel deve salvare/ripristinare la palette, proteggere i cinque colori della shell e gestire la proprietà globale prima di consentire modifiche alle app.

Mount/unmount di immagini disco, informazioni sui drive e SoftIEC: candidati per utility Commodore, con lease sui drive e impatto esplicito sui file in uso. Il percorso SoftIEC UCI documentato riguarda il drive virtuale dell'Ultimate, non equivale a un driver per ogni periferica IEC fisica. [Funzioni e copertura UCI](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md).

Configurazione globale, cambio IP/ora, freeze, reboot e caricamento/salvataggio completo della REU restano servizi amministrativi della shell. Caricare una REU mentre C-OS la usa sovrascrive anche kernel backing, superfici e processi: richiede un vero protocollo di uscita/ripristino, non una normale syscall app.
