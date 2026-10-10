# C-OS Commodore OS
## Specifica per la prima implementazione

Versione 0.1, revisione 4 — 10 ottobre 2026. Target: C64 Ultimate, PAL, turbo nominale a 64 MHz, REU da 16 MiB, video UPIC 320×200.

Versione numerica dell'ABI iniziale: 1, identica in header REU, SYS_INFO e descrittori SDK. Versioni del documento e ABI sono numerazioni distinte.

C-OS è un piccolo sistema operativo grafico con kernel e interprete in assembly 6510. Le applicazioni eseguono bytecode e accedono alla REU mediante indirizzi lineari a 24 bit. Il kernel controlla video, memoria, input e distribuzione del tempo CPU; nessuna applicazione deve cooperare affinché le altre continuino a funzionare.

La UI scelta è **C — NeXT libero**: desktop semplice, senza dock, taskbar o barra menu permanente; icone e widget quadrati liberamente collocabili su una griglia delle stesse dimensioni delle icone. La shell usa esclusivamente nero, bianco e i tre grigi del C64. La prima implementazione deve privilegiare semplicità, latenza dell'interazione e dimensione del codice.

Questa specifica definisce il comportamento da implementare. I valori indicati come **iniziali** sono parametri da misurare e affinare; non sono prestazioni già conseguite. La geometria scelta, l'indirizzamento lineare e la preemption delle app sono requisiti. Il layout interno della RAM e le dimensioni delle cache possono essere adattati documentando il motivo e mantenendo questi requisiti.

Fanno parte della specifica anche [C-Script: linguaggio e compilatore](LANGUAGE.md), [SDK e servizi Ultimate](ULTIMATE-API.md) e [numeri frazionari](NUMERICS.md). Il presente documento definisce VM, memoria, scheduling e shell; gli allegati definiscono sorgente delle app, API e profilo numerico. Sono contratti da implementare, non documentazione di funzionalità già esistenti.

Per il dev agent: partire dalla sezione 22 e dalle dipendenze delle milestone in §18. Le tabelle di questo documento sono normative per ISA e syscall core; ULTIMATE-API.md per binding, record SDK, eventi e servizi dispositivo; NUMERICS.md per rappresentazione e semantica numerica; LANGUAGE.md per tipizzazione e ABI delle funzioni. Aggiornare insieme i rimandi quando si cambia un contratto condiviso. I mockup sono riferimenti estetici, non sostituiscono dimensioni e comportamento qui definiti. La revisione 4 corregge il contratto ancora non implementato e mantiene ABI 1.

## 1 Decisioni e perimetro

| Tema | Decisione per la versione 0.1 |
|---|---|
| Nome | C-OS, Commodore OS |
| Hardware | C64 Ultimate con 16 MiB REU e turbo nominale 64 MHz |
| Video | PAL; UPIC realmente ristretto a 320×200; 16 colori indipendenti per pixel |
| Shell | NeXT minimale; desktop senza barre permanenti |
| Palette della shell | Indici C64 0, 1, 11, 12, 15 |
| Desktop | Celle 32×32; icone e widget occupano una cella intera |
| Runtime | VM a registri, implementata in assembly NMOS 6502/6510 |
| Memoria delle app | Indirizzi REU lineari a 24 bit, con controllo dei limiti |
| Multitasking | Un contesto VM per app; sospensione imposta dal dispatcher |
| Fuel | Contatore economico per opcode; scadenze video gestite separatamente |
| Processi simultanei | Massimo 4 nella prima versione |
| Finestre simultanee | Massimo 4, una per applicazione |
| Linguaggio iniziale | C-Script, piccolo linguaggio compilato in bytecode sul computer di sviluppo; assembler disponibile per test |
| Numeri frazionari | Float24 compatto e float32 più preciso; float è alias di float32; profilo COS-NUM-1 |
| Distribuzione iniziale | Bootstrap PRG e immagine REU generati insieme |
| API Ultimate | File e directory, metadati, storage e RTC tramite UCI; SID e Ultimate Audio mediante servizi del kernel |
| Video userspace | Superfici tramite handle, primitive native e blit da array di pixel dell'app; mapping diretto rinviato |
| Persistenza iniziale | Documenti e layout tramite il servizio file, quando lo storage è disponibile |

Non sono necessari per il primo MVP: POSIX, Linux, emulazione RISC-V, compatibilità binaria con altre VM, Lua, WAMR, JIT, garbage collector, rete, USB HID nativo, processi nativi non fidati, un filesystem scritto da zero o compilazione sul C64. File I/O, directory/stat, mkdir/rename/remove di file, scoperta storage, lettura RTC, SID, Ultimate Audio e compilatore C-Script fanno parte del perimetro; la disponibilità dei dispositivi viene comunicata alle app. Rete e HTTP hanno milestone successive definite nell'allegato SDK.

Non portare il modello event/update/render o lo scheduler di Freeview. Le applicazioni C-OS hanno un normale punto di ingresso e un contesto persistente; possono eseguire un event loop, attendere eventi o calcolare.

## 2 Risultato atteso del primo MVP

Il sistema deve avviarsi nel desktop, permettere di spostare le icone fra celle e aprire almeno due applicazioni VM. Un'applicazione in ciclo infinito e un'applicazione che accede continuamente alla REU devono poter convivere con input, finestre e desktop utilizzabili.

La dimostrazione deve includere:

- un'app Note in C-Script con buffer modificabile e apertura/salvataggio tramite il servizio file;
- un'app Contatore che aggiorna una parte limitata della propria finestra;
- un'app Stress che alterna calcolo e accessi oltre i primi 64 KiB;
- un monitor nativo che visualizza processi, fault, memoria e contatori diagnostici.

Fornire inoltre esempi C-Script di lettura/scrittura file, riproduzione SID e PCM tramite Ultimate Audio, e disegno da array lineare. Non devono tutti essere processi residenti contemporaneamente: il pack contiene al massimo quattro app, e il bundler deve poter generare un pack di demo alternativo. I servizi assenti restituiscono un errore esplicito; desktop e app senza dipendenze dal dispositivo continuano a funzionare.

Includere una demo di elenco directory con stat della voce selezionata e un pannello della shell per visualizzare/aggiornare lo storage rilevato. Verificare boot senza storage, scelta fra più root C-OS e orologio civile con fallback uptime. Sono sufficienti una lista semplice e i servizi descritti; un file manager completo non è richiesto.

Includere inoltre un piccolo pannello numerico C-Script: input testuale, scelta float24/float32, quattro operazioni e risultato formattato. Un loop di calcolo senza yield in un'altra app deve convivere con il pannello e il desktop. L'esempio dimostra i due tipi e la gestione degli errori; il confronto delle prestazioni vive nel benchmark separato.

Il nome “Files” presente nei mockup è un esempio visivo, non un requisito di implementare subito un file manager. Ogni icona attiva dell'MVP deve aprire una funzione reale; evitare pulsanti decorativi che non fanno nulla.

Il monitor della shell può aprire un pannello temporaneo gestito come un menu del compositor: non occupa un quinto processo o una quinta superficie di finestra. Deve restare raggiungibile quando tutti e quattro i processi sono occupati, e consentire di identificare e terminare quello attivo.

## 3 Hardware e fatti di partenza

La REU non è RAM direttamente indirizzabile dal 6510: il driver programma i trasferimenti fra REU e RAM locale. La VM rende questa distinzione invisibile alle app attraverso LOAD, STORE e puntatori lineari. I registri del DMA restano esclusivamente del kernel.

UPIC genera l'immagine scrivendo il colore del bordo in sincronia con il raster. Ridurre la larghezza libera memoria e lavoro per riga, ma un ciclo che aspetta comunque tutte le righe non restituisce automaticamente quel tempo alla VM. Il raster deve essere prodotto anche quando il desktop non cambia.

Riferimenti per i vincoli hardware: [documentazione turbo Ultimate](https://1541u-documentation.readthedocs.io/en/latest/config/turbo_mode.html), [manuale UPIC](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UPIC_MANUAL.md), [interfaccia Ultimate Audio](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.h). I dettagli da verificare per file, SID e audio sono nell'allegato SDK.

| Punto | Regola |
|---|---|
| Turbo | Verificare la velocità effettiva al boot; non fidarsi soltanto del valore di $D031 |
| Avvio | Attendere la disponibilità effettiva del turbo dopo il reset |
| PAL | Primo target; NTSC escluso dal profilo iniziale |
| DMA | Sincrono e non interrompibile dalla CPU; misurarne durata e costo di setup |
| Arbitraggio | Non assumere che il DMA diventi 64 volte più veloce grazie al turbo |
| Firmware | Registrare modello, versione, impostazioni e profilo di timing nei risultati |
| Emulazione | Utile per regressioni e diagnostica; non sostituisce la qualificazione del timing sul dispositivo |
| NMI e menu firmware | Disturbi esterni al normale scheduling; prevedere recupero del display e documentarne gli effetti |

Per la REU partire da FETCH/STASH immediati, indirizzi incrementanti, interrupt REU disabilitati, autoload disabilitato. Ogni transazione deve inizializzare esplicitamente i registri necessari. Una richiesta software di lunghezza zero è un no-op: non passarla come zero ai registri di lunghezza, dove può significare 65.536 byte.

## 4 Architettura

```text
Applicazioni in bytecode
    registri, indirizzi lineari, syscall
                    |
VM assembly + fuel + controlli di accesso
                    |
Kernel: scheduler, cache, code di eventi e lavori limitati
             /                     \
Window manager e disegno       Driver REU
             \                     /
          RAM locale e framebuffer
                    |
          Scanout UPIC a priorità massima
```

Il kernel e la shell sono codice nativo fidato. L'applicazione non può chiamare indirizzi 6510, modificare i vettori, toccare zero page o stack hardware, cambiare il turbo, programmare REU/VIC/CIA o accedere al framebuffer fisico.

C-Script viene compilato direttamente per questa VM; non aggiunge un secondo interprete. Il kernel possiede anche UCI, SID e Ultimate Audio. Le API possono sospendere l'app chiamante mentre il kernel serve le altre attività. I dettagli UPIC non fanno parte né del linguaggio né dell'ABI video.

La VM non emula un'intera macchina: nessun chipset, MMU hardware, timer guest o istruzioni privilegiate. Il suo stato consiste in registri, PC, stack virtuale e metadati del processo.

## 5 RAM locale e framebuffer

### 5.1 Bilancio

| Risoluzione | Pixel packed 4 bpp | Riserva con colonne da 256 byte |
|---|---:|---:|
| 384×200 | 38.400 byte | 49.152 byte |
| 360×200 | 36.000 byte | 46.080 byte |
| 320×200 | 32.000 byte | 40.960 byte |

C-OS parte dalle colonne da 256 byte: letture indicizzate prevedibili, nessun attraversamento di pagina con Y fra 0 e 199. I 56 byte non visualizzati di ogni colonna restano inutilizzati nell'MVP.

Dei 64 KiB locali, 40 KiB sono framebuffer e 4 KiB sono la finestra I/O visibile. Restano **20 KiB direttamente utilizzabili** per codice, stack, cache e dati, mantenendo I/O visibile. I 24 KiB “fuori dal framebuffer” non sono tutti RAM normalmente accessibile.

### 5.2 Mappa iniziale

ROM BASIC/KERNAL escluse e I/O visibile durante il normale funzionamento, con configurazione del port 6510 coerente con $01=$35.

| Intervallo inclusivo | Byte | Uso iniziale |
|---|---:|---|
| $0000–$0001 | 2 | Registri del port 6510 |
| $0002–$007F | 126 | Registri VM attivi e scratch del dispatcher |
| $0080–$00BF | 64 | Scratch kernel e driver |
| $00C0–$00FF | 64 | Scratch riservato al raster e agli interrupt |
| $0100–$01FF | 256 | Stack hardware, solo kernel |
| $0200–$02FF | 256 | Tabella di estrazione del nibble alto |
| $0300–$03FF | 256 | Stato globale e descrittori compatti delle finestre |
| $0400–$05FF | 512 | Quattro PCB da 128 byte |
| $0600–$07FF | 512 | Quattro code eventi, 8 record da 16 byte ciascuna |
| $0800–$0BFF | 1.024 | Cache codice: due linee da 128 byte per processo |
| $0C00–$0FFF | 1.024 | Cache dati condivisa: otto linee da 128 byte |
| $1000–$11FF | 512 | Buffer temporanei di DMA e lavori grafici |
| $1200–$3FFF | 11.776 | Codice residente kernel, VM, shell e driver |
| $4000–$CFFF | 36.864 | Prime 144 colonne packed del framebuffer |
| $D000–$DFFF | 4.096 | I/O; non usarlo come normale RAM |
| $E000–$EFFF | 4.096 | Ultime 16 colonne packed del framebuffer |
| $F000–$F9FF | 2.560 | Renderer UPIC, preparazione e sincronizzazione |
| $FA00–$FCFF | 768 | Font residente, 96 glifi da 8 byte |
| $FD00–$FD7F | 128 | Save-under del cursore |
| $FD80–$FDFF | 128 | Metadati delle cache |
| $FE00–$FFF9 | 506 | Stato desktop, dirty list, titoli e diagnostica |
| $FFFA–$FFFF | 6 | Vettori NMI, RESET e IRQ |

È un budget di progetto da confrontare con la prima map file, non una misura del kernel finito. Se una sezione non entra, il build deve fallire: niente sovrapposizioni silenziose, banking temporaneo dell'I/O nel raster o sottrazione implicita di memoria alla VM.

Le strutture hanno limiti fissi. Generare un report con dimensione effettiva di ogni sezione, occupazione massima dello stack hardware e margine residuo. Non aggiungere un framework UI prima di avere questo report.

Il budget comprende anche i driver aggiunti nell'allegato SDK: non assumere spazio extra oltre la mappa. Tenere in REU metadati freddi, nomi dei file e librerie bytecode; mantenere residenti soltanto dispatcher, driver e continuazioni necessari. La dimensione del kernel completo è un rischio da verificare presto. Se non entra, ridurre duplicazioni e spostare logica non privilegiata in bytecode, oppure proporre una revisione misurata della mappa; non eliminare silenziosamente servizi richiesti.

Il nucleo numerico per float24/float32 e il suo scratch rientrano nello stesso budget. NUMERICS.md pone un obiettivo iniziale da qualificare di 4 KiB complessivi per nucleo, conversioni numeriche e bridge; i convertitori testuali iniziano in bytecode nelle arene REU delle app. Non aggiungere 4 KiB alla mappa come se fossero memoria libera esterna al limite.

### 5.3 Accesso al framebuffer

Per x fra 0 e 319 e y fra 0 e 199:

```text
c = x >> 1
base(c) = $4000 + 256*c                  se c < 144
base(c) = $E000 + 256*(c-144)            altrimenti
indirizzo = base(c) + y
x pari: nibble basso; x dispari: nibble alto
```

Le primitive devono preservare il nibble del pixel adiacente. La geometria e le colonne devono essere ristrette davvero a 320: una viewport da 320 dentro un renderer da 384 non soddisfa questo requisito.

## 6 Memoria REU lineare e isolamento

### 6.1 Modello scelto

Lo spazio numerico degli indirizzi è $000000–$FFFFFF. Un puntatore contiene esattamente tre byte, little endian.

Nell'MVP **l'indirizzo dell'app coincide con l'offset REU**. Non introdurre una tabella di pagine virtuali o una somma della base del processo per ogni accesso. Il loader assegna a ogni applicazione un'arena contigua; l'assembler/linker sul computer di sviluppo risolve i riferimenti alla base assegnata.

Questa scelta dà indirizzamento lineare e un controllo di appartenenza semplice. Non offre spazi privati tutti basati a zero né overcommit. I 16 MiB sono la memoria fisica totale condivisa: non 16 MiB dedicati a ciascuna app.

Un array può attraversare $xxFFFF senza istruzioni di cambio banco. LOAD/STORE, copia, stack, codice e API accettano gli stessi puntatori.

### 6.2 Riserva del sistema

| Intervallo REU inclusivo | Dimensione | Destinazione iniziale |
|---|---:|---|
| $000000–$00FFFF | 64 KiB | Header, immagini del kernel, seed delle app e asset di boot |
| $010000–$017FFF | 32 KiB | Superficie client della finestra 1 |
| $018000–$01FFFF | 32 KiB | Superficie client della finestra 2 |
| $020000–$027FFF | 32 KiB | Superficie client della finestra 3 |
| $028000–$02FFFF | 32 KiB | Superficie client della finestra 4 |
| $030000–$033FFF | 16 KiB | Snapshot directory 1 |
| $034000–$037FFF | 16 KiB | Snapshot directory 2 |
| $038000–$03FFFF | 32 KiB | Asset shell, configurazione, metadati freddi e riserva del sistema |
| $040000–$FFFFFF | 15,75 MiB | Arene delle applicazioni |

La riserva iniziale del sistema è quindi 256 KiB. Esporla nei report; non descrivere 15,75 MiB liberi come 16 MiB effettivamente allocabili dalle app. Il confine può essere rivisto dopo misure, mantenendo lo spazio lineare a 24 bit.

Le snapshot directory riutilizzano 32 KiB della riserva originaria; non aumentano il limite di RAM residente del 6510. Il report di build deve dimostrare che asset shell e metadati entrino nei 32 KiB rimanenti. Slot e memoria delle snapshot tornano disponibili dopo closedir, kill o fallimento di opendir.

### 6.3 Arena di un processo

Ogni arena contiene codice immutabile, dati inizializzati/BSS, heap e stack virtuale separato. Inizio e dimensione dell'arena, inizi delle sezioni e dimensione dello stack sono multipli di 128 byte; il codice è anche allineato a quattro byte. Heap e stack contengono almeno 128 byte ciascuno. Il manifest dichiara tutti i limiti. Due arene non condividono mai una linea cache fisica.

Dati inizializzati e BSS possono essere vuoti: descriverli con inizio e lunghezza, con lunghezza zero che non autorizza accessi o copie. Le regioni con limiti inclusivi elencate sotto sono invece sempre non vuote. Il padding di allineamento non è codice eseguibile e non fa parte della lunghezza dei dati da ripristinare.

Il kernel conserva limiti **inclusivi a 24 bit**: arena_first/last, code_first/last, heap_first/last, stack_first/last. Questo evita di dover rappresentare $1000000 in un puntatore a 24 bit.

Per un accesso di N byte con N>0:

1. Calcolare last = address + N - 1 con rilevamento dell'overflow.
2. Verificare address >= arena_first e last <= arena_last.
3. Per una scrittura, verificare che l'intervallo non intersechi il codice o un campione audio attualmente protetto dal kernel.
4. Per fetch/branch/return, verificare che il target sia allineato a quattro e che tutti e quattro i byte dell'istruzione siano nel codice.

Non troncare il riporto oltre 24 bit. Il kernel può indirizzare la propria riserva, ma l'app non può farlo, neppure attraverso una syscall.

Un puntatore fuori arena può essere costruito o conservato come valore; il suo dereferenziamento è vietato. Questo mantiene semplici confronti e aritmetica senza indebolire l'accesso alla memoria.

### 6.4 Heap e ciclo di vita

Niente GC nell'MVP. Fornire inizialmente una libreria userspace con bump allocator e reset dell'arena heap quando l'app riparte; malloc/free generale può arrivare successivamente.

Al riavvio della stessa app ripristinare i dati inizializzati, azzerare BSS e contesto, e ricreare stack e risorse. Il contenuto dell'heap non è garantito zero. Le arene dell'MVP sono assegnate staticamente e non vengono riassegnate a un'altra app durante la sessione.

Prima di un'eventuale futura riassegnazione a un'altra app, azzerare la regione. Terminando un processo, annullare i lavori pendenti e invalidare tutte le linee cache e gli handle che gli appartengono prima di riutilizzare lo slot.

Prima di riutilizzare memoria letta dall'hardware audio, fermare i canali e rilasciare i relativi vincoli. Un'operazione UCI già inviata può richiedere drenaggio/abort e non va attribuita al nuovo processo che occupa lo stesso slot. La terminazione ha una continuazione di cleanup del kernel, distinta dal contesto VM ormai fermo.

## 7 Cache e transazioni REU

### 7.1 Cache iniziali

- Codice: due linee da 128 byte per processo, sola lettura; sostituzione alternata o LRU a un bit.
- Dati: otto linee da 128 byte totali, write-back; sostituzione CLOCK semplice.
- Tag: indirizzo REU del blocco e stato valid/dirty/busy; i dati sporchi restano associati al proprietario.
- Pagina REU qui significa soltanto un blocco di cache, non una finestra visibile all'app.

Le dimensioni sono parametri di build da confrontare almeno con una variante a linee da 64 byte. Non introdurre cache associative complesse senza misure di un problema reale.

### 7.2 Miss e ripresa

Un cache miss porta il processo in WAIT_REU e restituisce il controllo al kernel. Il kernel effettua write-back/refill in transazioni limitate quando il calendario video lo permette.

La linea di destinazione resta busy e non utilizzabile fino al completamento del trasferimento. Solo allora pubblicare il tag valido e risvegliare il processo.

Prima di modificare registri, stack o memoria, un opcode deve avere verificato tutti i limiti e reso disponibili tutte le linee necessarie. LOAD/STORE di 16 o 24 bit possono attraversare due linee: fissarle entrambe per la breve fase di esecuzione.

Se manca una linea, riprendere dallo stesso PC senza aver cambiato stato visibile. Questo evita STORE parziali, PUSH duplicati, doppie syscall e consumo ripetuto del fuel sul medesimo tentativo.

### 7.3 Coerenza fra VM e servizi nativi

Non servono flush completi a ogni context switch. Tuttavia driver e servizi nativi non possono leggere dalla REU una copia vecchia di dati ancora sporchi in cache.

Tutti gli accessi nativi alla memoria dell'app devono:

- usare lo stesso livello di accesso coerente della VM; oppure
- scrivere le linee dirty interessate prima della lettura DMA e invalidare/aggiornare le linee interessate da una scrittura DMA.

La seconda strada deve essere centralizzata nel driver, non replicata in ogni syscall. I buffer delle superfici appartengono al kernel e usano staging separato dalla cache dati delle app.

### 7.4 Driver DMA

Un solo arbitro possiede i registri REU. Ogni richiesta dichiara direzione, indirizzo REU, indirizzo locale, lunghezza, proprietario e continuazione.

Il driver:

- non trasferisce mai su I/O, codice, zero page o stack hardware per conto di un'app;
- evita il wrap dell'indirizzo locale a 16 bit e quello REU a 24 bit;
- spezza i trasferimenti secondo il budget temporale, non soltanto secondo il limite dei registri;
- tratta FETCH e STASH come operazioni sincrone distinte, con costi propri;
- non avvia un DMA se non può terminare prima del guard time del video.

Valore iniziale conservativo: transazioni fino a 128 byte durante il normale servizio. Il profilo hardware può ridurle o ampliarle sulla base delle misure. Una lunghezza massima non sostituisce il controllo del tempo disponibile.

## 8 VM e bytecode

### 8.1 Stato architetturale

| Stato | Dimensione | Uso |
|---|---:|---|
| R0–R7 | 8 × 16 bit | Interi, contatori, handle e argomenti |
| P0–P3 | 4 × 24 bit | Puntatori lineari |
| PC | 24 bit | Indirizzo dell'opcode corrente |
| SP | 24 bit | Prossimo byte libero dello stack virtuale discendente |
| Fuel | 8 bit | Istruzioni ancora ammesse nella slice corrente |
| PCB | Metadati separati | Limiti, stato, attese, eventi, lavori e diagnostica |

R e P del processo attivo risiedono in zero page; al cambio processo vengono copiati nel PCB. Le app non accedono direttamente a questa zero page.

Non esistono flag aritmetici persistenti della VM: i branch confrontano registri. Gli interi sono little endian; i valori signed a 16 bit usano complemento a due. ADD/SUB sugli interi fanno wrap modulo 65.536; l'aritmetica dei puntatori controlla invece l'overflow a 24 bit.

### 8.2 Codifica iniziale

Ogni istruzione occupa **quattro byte**: opcode, b1, b2, b3. PC e destinazioni di controllo sono allineati a quattro.

È una scelta iniziale per decoder, fetch e validazione semplici. Consuma più codice di un bytecode variabile, ma evita decodifica delle lunghezze e bitmap delle destinazioni. Misurare esplicitamente il traffico REU del codice; non dichiarare questo formato il più veloce senza confronto.

Regole degli operandi:

- rr: b1 basso nibble = destinazione/lhs; alto nibble = sorgente/rhs; indici R validi 0–7.
- pp: stesso schema per P, indici validi 0–3.
- rp: basso nibble = R; alto nibble = P.
- pr: basso nibble = P; alto nibble = R.
- u16/i16: b2 basso, b3 alto.
- u24: b1 basso, b2 medio, b3 alto.
- Un singolo registro R/P occupa tutto b1 come indice unsigned, salvo posizione esplicitamente diversa nella tabella; indici R>7 o P>3 sono invalidi. Nei formati a nibble verificare separatamente entrambi gli indici.
- Campi non usati devono essere zero; codifiche riservate generano fault.

Per i branch relativi: target = PC + 4 + 4 × sign_extend(i16). Il calcolo usa un intermedio sufficientemente largo e non deve avvolgersi a 24 bit.

Quando un'istruzione continua, validare il prossimo PC effettivamente scelto prima degli effetti; un branch non preso usa PC+4. CALL valida anche PC+4 come futuro indirizzo di ritorno prima del push. JMP/RET e terminazione non richiedono un fall-through valido. Per una syscall che può ritornare, il PC di ripresa deve essere valido prima di accettare il lavoro. Il compilatore chiude ogni percorso con RET, EXIT o TRAP e non lascia esecuzione implicita oltre il codice.

### 8.3 Set di istruzioni iniziale

Tutti gli opcode validi costano un'unità di fuel nella versione 0.1. Le operazioni native sono contabilizzate separatamente.

| Hex | Istruzione | Operandi | Semantica |
|---|---|---|---|
| 00 | NOP | zero | Nessun effetto |
| 01 | MOV | rr | Rdst = Rsrc |
| 02 | LDI | Rdst, u16 | Carica una costante a 16 bit |
| 03 | ADD | rr | Rdst += Rsrc |
| 04 | SUB | rr | Rdst -= Rsrc |
| 05 | AND | rr | AND bit a bit |
| 06 | OR | rr | OR bit a bit |
| 07 | XOR | rr | XOR bit a bit |
| 08 | SHL | Rdst, b2=count | Shift sinistro, count 0–15 |
| 09 | SHR | Rdst, b2=count | Shift destro logico, count 0–15 |
| 0A | SAR | Rdst, b2=count | Shift destro aritmetico, count 0–15 |
| 0B | ADDI | Rdst, u16 | Somma immediata modulo 65.536 |
| 0C | TRUNC8 | Rdst | Azzera gli 8 bit alti |
| 0D | SEXT8 | Rdst | Estende il segno degli 8 bit bassi |
| 0E | NOT | Rdst | Complemento a 16 bit |
| 10 | LD8 | rp, u16 | R = zero_extend(mem[P+u16]) |
| 11 | LD16 | rp, u16 | R = lettura little endian di due byte |
| 12 | ST8 | rp, u16 | Scrive gli 8 bit bassi di R |
| 13 | ST16 | rp, u16 | Scrive due byte di R |
| 14 | LDP | pp, u16 | Pdst = tre byte da [Psrc+u16] |
| 15 | STP | pp, u16 | Scrive P basso nibble a [P alto nibble + u16] |
| 16 | PMOV | pp | Pdst = Psrc |
| 17 | PADD | pr | Pdst += unsigned(Rsrc), con overflow controllato |
| 18 | PSUB | pr | Pdst -= unsigned(Rsrc), con underflow controllato |
| 19 | PGETLO | rp | R = 16 bit bassi di P |
| 1A | PGETHI | rp | R = 8 bit alti di P, zero-extended |
| 1B | PMAKE | b1=Pdst, b2=Rlo, b3=Rhi | P = Rlo + (Rhi << 16); Rhi deve essere <=255 |
| 1C–1F | PLI0–PLI3 | u24 | Carica un puntatore immediato nel P indicato dall'opcode |
| 20 | JMP | u24 | Salta a un indirizzo assoluto |
| 21 | CALL | u24 | Salva PC+4 sullo stack e salta |
| 22 | RET | zero | Recupera e valida il PC di ritorno |
| 23 | BEQ | rr, i16 | Branch se i due R sono uguali |
| 24 | BNE | rr, i16 | Branch se diversi |
| 25 | BLTU | rr, i16 | Branch se lhs < rhs unsigned |
| 26 | BGEU | rr, i16 | Branch se lhs >= rhs unsigned |
| 27 | BLTS | rr, i16 | Branch se lhs < rhs signed |
| 28 | BGES | rr, i16 | Branch se lhs >= rhs signed |
| 29 | PBEQ | pp, i16 | Confronto di uguaglianza a 24 bit |
| 2A | PBNE | pp, i16 | Confronto di disuguaglianza a 24 bit |
| 2B | PBLTU | pp, i16 | Confronto unsigned dei puntatori |
| 2C | PBGEU | pp, i16 | Confronto unsigned dei puntatori |
| 30 | PUSH16 | Rsrc | Push di due byte |
| 31 | POP16 | Rdst | Pop di due byte |
| 32 | PUSHP | Psrc | Push di tre byte |
| 33 | POPP | Pdst | Pop di tre byte |
| 34 | GETSP | Pdst | Copia SP |
| 35 | SETSP | Psrc | Imposta SP entro i limiti dello stack |
| 36 | SYSCALL | b1=id | Invoca un servizio del kernel |
| 37 | YIELD | zero | Termina volontariamente la slice |
| 38 | TRAP | b1=0, u16 | Fault esplicito dell'app |

Moltiplicazione, divisione e operazioni intere a 32 bit iniziano come librerie di bytecode. Non aggiungere un opcode con lavoro arbitrariamente lungo per accelerarle. I float usano il servizio NUM_OP con lavoro nativo contabilizzato e limitato, secondo NUMERICS.md; l'ISA non acquisisce registri F o opcode floating point monolitici.

### 8.4 Stack e chiamate

Stack discendente nella REU. SP iniziale = stack_last. Per PUSH di N byte:

```text
verificare SP-(N-1) >= stack_first
scrivere il valore little endian in [SP-(N-1), SP]
SP = SP-N
```

Per POP di N byte verificare SP+N <= stack_last, leggere [SP+1, SP+N] e incrementare SP di N. A stack pieno SP = stack_first-1; a stack vuoto SP = stack_last. L'arena delle app inizia ben sopra zero, quindi entrambi sono rappresentabili a 24 bit.

CALL usa un PUSH di tre byte; RET valida il target prima di modificare PC o SP. GETSP/SETSP consentono frame e locali software; SETSP accetta soltanto [stack_first-1, stack_last].

L'ISA non salva automaticamente alcun registro oltre al PC di CALL. L'ABI C-Script aggiunge via prologo/epilogo la conservazione di P2, come definito in LANGUAGE.md. Nessun byte dello stack virtuale viene conservato sullo stack hardware fra slice o attese.

### 8.5 Fault

Un opcode invalido, un PC non allineato, un accesso illecito, overflow dei puntatori, stack overflow/underflow o TRAP terminano solo il processo responsabile.

Registrare PID, PC dell'istruzione, causa e indirizzo coinvolto. Annullare le sue attese, invalidare gli handle e rimuovere la finestra tramite il normale compositor. Il monitor deve restare utilizzabile.

## 9 Fuel e scheduler

### 9.1 Regola di preemption

Quantum iniziale: **128 opcode ritirati**. Il dispatcher ha un controllo obbligatorio che l'app non può saltare. Non servono yield inseriti dal compilatore e non esistono debug hook.

Sequenza logica:

```text
se fuel == 0: restituire FUEL_EXHAUSTED al kernel
fetch e decodifica
verifica limiti, risorse e linee cache
se serve I/O: restituire WAIT senza effetti architetturali
decrementare fuel una sola volta
eseguire una fase limitata e completare l'istruzione
pubblicare PC successivo o stato di attesa della syscall
```

Il kernel può interrompere la slice anche per una scadenza video o un evento prioritario. Nel caso di sola sospensione temporale, conservare il fuel residuo. Un miss non consuma di nuovo fuel al retry.

SYSCALL avanza il PC una sola volta quando il kernel accetta il lavoro e ne conserva una continuazione. Alla ripresa si consegna il risultato; non si riesegue l'invocazione.

### 9.2 Stati del processo

STOPPED, RUNNABLE, WAIT_REU, WAIT_JOB, WAIT_EVENT, SLEEPING, FAULTED.

Non lasciare un processo WAIT nelle liste eseguibili. La conclusione di I/O, un evento o la scadenza di sleep lo riporta a RUNNABLE. Ogni app ha al massimo una syscall/lavoro bloccante pendente.

### 9.3 Politica iniziale

Round-robin fra i processi RUNNABLE, con medesimo quantum e senza priorità dinamiche. Il risveglio inserisce il processo in coda e non gli assegna una scorciatoia per eseguire ripetutamente prima degli altri.

Un nuovo quantum completo si assegna all'esaurimento o dopo un'attesa effettiva di evento, sleep positivo o I/O esterno. Cache miss e sospensioni per lavoro CPU interno non ricaricano il budget: questa regola vale anche per MEM_COPY/FILL, disegno, presentazione e creazione di superfici.

NUM_OP è lavoro CPU: le sue continuazioni conservano il fuel residuo anche se attraversano più finestre di servizio. Attendere la coda numerica non equivale a una nuova attivazione da I/O esterno. Il costo delle fasi viene registrato nel budget nativo del proprietario, con la normale rotazione dei lavori.

YIELD e SLEEP(0) rinunciano al fuel residuo e inseriscono l'app in fondo alla coda; il turno seguente parte con il quantum normale. Un poll che restituisce subito EAGAIN non è una vera attesa e non ricarica il fuel. Ridurre una slice per la scadenza raster significa limitarne gli opcode eseguibili adesso, senza cancellare o aumentare il credito residuo del turno.

La coda dei lavori nativi viene servita anch'essa a rotazione, **un pezzo limitato per proprietario alla volta**. Una grande copia o un enorme riempimento non monopolizzano il servizio. Registrare separatamente opcode ritirati, byte DMA e tempo nativo per processo.

Quando entrambe hanno lavoro ammissibile prima della scadenza raster, alternare una slice VM e un pezzo della coda nativa; conservare il turno fra finestre di servizio. Se una coda è vuota o il suo prossimo pezzo non entra nel tempo residuo, servire l'altra senza perdere il turno dovuto. La shell partecipa come proprietario dei lavori ordinari, inclusa la composizione: due code round-robin separate non bastano se una viene sempre servita prima dell'altra.

NUM_OP, copie, riempimenti e disegno passano da questo arbitraggio anche quando basta un solo pezzo: un percorso rapido non deve eseguire una serie di lavori nativi dentro la stessa slice VM aggirando la rotazione. Le query di metadati a costo piccolo e fisso possono completare nel gestore della syscall, includendo quel costo nel limite dell'opcode.

Input, cursore e interazione con la shell hanno precedenza rispetto al lavoro ordinario, ma sono anch'essi limitati. Coalescere i movimenti del puntatore e aggiornare i widget lenti solo quando cambiano. Non aggiungere subito DWRR, schedulazione per basic block o stime adattive complesse.

### 9.4 Fuel e tempo reale

Un opcode non equivale a una durata costante. Il fuel limita la monopolizzazione della VM; il calendario video limita quando si può avviare lavoro.

Prima di una slice, il kernel può ridurne il quantum in base al tempo disponibile e al peggior costo misurato degli opcode senza miss. Le vie lente tornano al kernel prima di avviare DMA o altro lavoro lungo.

Mantenere una stima conservativa del costo massimo di ogni pezzo nativo e un guard time prima del video. Se un pezzo non entra, rinviarlo al periodo utile seguente. Non usare una media del tempo di DMA come limite superiore di sicurezza.

## 10 Calendario video e interrupt

### 10.1 Prima implementazione

Il raster UPIC ha precedenza assoluta. Durante le 200 righe visualizzate non eseguire la VM e non avviare DMA REU. Il lavoro principale si svolge prima e dopo questo intervallo.

Il passaggio da 384 a 320 pixel non abbrevia le 200 righe. Nella prima versione i margini orizzontali possono restare attese: l'MVP deve già dimostrare responsività in questa configurazione semplice.

Solo dopo la qualificazione si potranno sostituire parti delle attese con lavori nativi a durata nota. Eseguire bytecode generico nei margini orizzontali è fuori dall'MVP.

### 10.2 Renderer

Usare come riferimento il passo dei pixel corretto di UPIC 1.3: la variante a 320 pixel ha 160 coppie, 20 caricamenti immediati da preparare e 2.520 cicli nel solo flusso dei pixel. Preparazione, sincronizzazione e chiusura sono costi aggiuntivi.

Non copiare indiscriminatamente i ritardi della variante 384 o quelli calibrati nell'emulatore. Verificare i pixel ai quattro bordi, l'allineamento e l'assenza di righe saltate sul profilo scelto. [Descrizione del timing UPIC](https://github.com/xahmol/mandelbrot-upic/blob/main/docs/UPIC_VIEWER.md).

L'IRQ deve preservare A/X/Y e tutte le risorse condivise che usa; lo scratch raster deve essere separato da quello VM. L'interprete e il kernel devono usare esclusivamente istruzioni NMOS 6502/6510 supportate.

### 10.3 Scadenze

Armare l'IRQ abbastanza prima della prima riga utile per sincronizzare la fase. Un valore iniziale di due righe di guardia è da verificare, non da assumere sufficiente a priori.

La regola fondamentale è: nessun DMA ancora attivo quando il raster deve sincronizzarsi. SEI non risolve questo problema; un DMA può trattenere la CPU oltre la scadenza.

L'IRQ costituisce anche un'interruzione del codice nativo in corso. Il cambio di processo VM avviene però solo a un confine consistente dell'interprete, non nel mezzo di un handler.

Disabilitare le sorgenti CIA non necessarie. Un NMI esterno può disturbare il timing: il gestore deve conservare lo stato, richiedere eventualmente recupero/emergenza e risincronizzare al frame successivo. Non promettere assenza di disturbi mentre si apre il menu firmware o si genera un NMI esterno.

## 11 UI scelta e griglia del desktop

### 11.1 Direzione visiva approvata

Riferimento selezionato: [mockup C, NeXT libero](ui/mockups/C-next-libero.png). I mockup [A](ui/mockups/A-classico-compatto.png) e [B](ui/mockups/B-next-dock.png) sono soltanto alternative archiviate.

Il desktop ha un fondo uniforme, poche icone quadrate e piccoli widget. Non riserva spazio a taskbar, dock, barra menu globale o pannelli permanenti. Le finestre possono sovrapporsi alle icone; un comando “Mostra desktop” permette di raggiungerle.

Il PNG rappresenta lo stile, non una specifica dei pixel. Font, icone, posizioni e colori devono essere ridisegnati sulla griglia reale del renderer. Le correzioni testuali di questa specifica prevalgono sul mockup, in particolare per il movimento a celle intere.

### 11.2 Palette

| Nome | Indice C64 | Uso |
|---|---:|---|
| Nero | 0 | Testo, contorni, selezione, titlebar attiva |
| Bianco | 1 | Testo su nero, campi, luce dei bordi |
| Grigio scuro | 11 | Ombre nette e contorni secondari |
| Grigio medio | 12 | Fondo desktop e stati inattivi |
| Grigio chiaro | 15 | Superfici di icone, pulsanti e pannelli |

Tutti i pixel della shell, inclusi cursore, icone, widget, menu e finestre di sistema, devono usare questi cinque indici. Le applicazioni possono usare gli altri colori **all'interno della propria area client**.

Niente gradienti, trasparenza, antialiasing, ombre sfumate, interlacciamento o dithering temporale. Un pattern spaziale binario è ammesso solo quando serve a distinguere selezione/focus. Non usare XOR arbitrario sugli indici, perché potrebbe generare colori fuori palette.

Non fissare gli RGB del dispositivo ai valori dei PNG generati: i riferimenti normativi sono gli indici C64, la loro funzione e il contrasto. La palette hardware corrente può influire sulla resa RGB.

### 11.3 Celle delle stesse dimensioni delle icone

**La cella misura 32×32 pixel, esattamente come l'intero riquadro di un'icona o widget. Non esiste uno snap a 8×8 per il desktop.**

A 320×200:

- 10 colonne, col = 0…9;
- 6 righe, row = 0…5;
- origine della griglia: x=0, y=4;
- posizione del riquadro: x=32×col, y=4+32×row;
- 4 pixel di margine sopra e sotto;
- ogni oggetto occupa una cella; nessuna sovrapposizione fra oggetti desktop.

Il movimento è come spostare un pezzo fra caselle di una scacchiera: l'oggetto passa da una cella all'altra. Non sono imposti movimenti diagonali o verso caselle adiacenti: col mouse si può raggiungere qualsiasi cella libera.

Il riquadro da 32×32 comprende bordo, icona e breve etichetta. Il disegno principale deve restare semplice; etichette di norma entro quattro caratteri con font 6×8. Usare nomi brevi o icone comprensibili, senza ridurre il testo sotto la dimensione leggibile.

Gli oggetti adiacenti occupano celle contigue. Se serve separazione visiva, ottenerla all'interno del riquadro, non cambiando il passo della griglia.

### 11.4 Trascinamento

1. Pressione sull'icona: selezionarla e memorizzare la cella sorgente.
2. Dopo una piccola soglia iniziale del puntatore, entrare in drag; annullare l'eventuale doppio click.
3. Calcolare la cella candidata dalla posizione del riquadro, conservando l'offset iniziale di presa. Arrotondare alla cella più vicina e limitare col/row all'intervallo valido.
4. Mostrare l'anteprima **già agganciata alla cella**; evitare che l'icona definitiva vaghi fra posizioni non valide.
5. Al rilascio in una cella libera, aggiornare il record e invalidare solo le aree necessarie.
6. Su una cella occupata da un altro oggetto, lasciare l'oggetto nella posizione originale. Niente scambio, riordino o spostamento automatico degli altri.
7. RUN/STOP annulla il drag. La cella sorgente è valida per annullare senza effetti.

Il drag è gestito dal kernel e deve funzionare anche se un'app VM è bloccata. Icone e widget seguono esattamente le stesse regole.

Sul desktop F5 seleziona l'oggetto successivo e F6 (Shift+F5 fisico) il precedente, in ordine riga/colonna con ritorno all'inizio; entrando nel desktop senza selezione scegliere il primo oggetto. RETURN apre l'oggetto selezionato. C=+M entra nella modalità “Sposta”: i cursori muovono la cella candidata, RETURN conferma e RUN/STOP annulla. Valgono le stesse regole di occupazione e limiti del mouse. Le associazioni sono costanti del driver/shell; un editor delle scorciatoie non è richiesto nell'MVP.

Click singolo seleziona; doppio click apre/ripristina un'app o attiva il widget. Soglia iniziale del doppio click: 12 frame PAL, da rifinire con una prova d'uso. La distanza e il trascinamento hanno precedenza sull'apertura.

### 11.5 Oggetti e layout

Capacità iniziale: 12 oggetti desktop, pur essendoci 60 celle. Gli oggetti iniziali sono un launcher per ciascuna delle 0–4 app effettivamente presenti nel pack e due widget: orologio/uptime e monitor di sistema.

Ogni record contiene almeno ID stabile, tipo, app/widget associato, colonna, riga e flag. La posizione non dipende dall'ordine della lista o dalla posizione delle finestre.

Layout iniziale suggerito: app nelle celle (0,0), (1,0), (0,1), (1,1); widget nelle celle (9,0), (9,1). L'utente può modificarlo liberamente.

In sessione, il layout resta in memoria. Salvarlo tramite il servizio file dopo un periodo di inattività iniziale di 50 frame dall'ultimo spostamento, non a ogni passo del drag. Il formato versionato contiene ID e coordinate, separati dal codice della shell. Validare dimensioni, duplicati e collisioni; un file invalido lascia attivo un layout valido di default. Storage assente o errore di scrittura non bloccano il desktop; segnalarli nel monitor e conservare lo stato di sessione. Formato e recupero sono definiti nell'allegato SDK.

I widget dell'MVP sono nativi e con lavoro limitato. L'orologio usa la cache RTC condivisa, aggiornata dal driver a bassa priorità; se il campione è assente o scaduto mostra chiaramente l'uptime, senza presentarlo come ora civile. Le chiamate delle app all'ora non generano una richiesta UCI ciascuna. Il monitor si aggiorna al massimo alcune volte al secondo. Widget userspace estensibili sono successivi.

### 11.6 Font e controlli

Font iniziale monospaziato 6×8, con glifo utile fino a 5×7 e spaziatura. Conservare 8 byte per glifo, 96 glifi. Testo ASCII stampabile nell'MVP; caratteri non supportati diventano un glifo sostitutivo.

Metriche iniziali:

| Elemento | Dimensione logica |
|---|---|
| Icona/widget desktop | 32×32, una cella |
| Font | 6×8 |
| Bordo finestra | 2 pixel |
| Barra titolo | 12 pixel, all'interno dei bordi |
| Pulsante comune | Altezza 14 pixel |
| Voce di menu | Altezza 12 pixel |
| Cursore | Massimo 12×16 pixel |
| Finestra minima | 128×80 |
| Finestra tipica | 240×152 |
| Finestra massima | 320×200 |

Il titolo attivo è nero con testo bianco. Superfici chiare e bordi netti a uno/due pixel richiamano NeXT senza imitarne le dimensioni originali. Pulsanti, selezioni e focus devono essere leggibili con i soli cinque toni.

Per l'MVP bastano testo, pulsante, checkbox, lista semplice e campo di testo monoriga. Il comportamento dei controlli client può vivere nella piccola libreria userspace; la shell gestisce nativamente menu e controlli propri. Non introdurre un albero di widget generico, layout engine o skin dinamiche.

## 12 Finestre e composizione

### 12.1 Window manager

Massimo quattro finestre, una per app, con ordine Z esplicito, focus, spostamento, chiusura e nascondimento. I menu sono contestuali o locali alla finestra.

Non applicare la griglia del desktop alle finestre. Per semplificare il primo blitter si possono usare origini X pari e Y intere; il movimento deve risultare comprensibile e coerente.

La prima versione può avere dimensioni fissate dall'app alla creazione. Il ridimensionamento interattivo e il maximize con reflow sono successivi, non prerequisiti del multitasking.

Durante lo spostamento usare un contorno o un'anteprima limitata; ricomporre il contenuto alla conferma. Evitare di copiare tutta la superficie REU a ogni movimento del mouse.

F1 alterna “Mostra desktop” e ripristino della disposizione precedente; F3 porta in primo piano la prossima finestra. Non modificare l'esecuzione delle app solo perché le finestre vengono nascoste.

Il launcher di un'app già attiva ripristina/porta avanti la sua finestra; non avvia duplicati nell'MVP. Se il processo è vivo ma ha chiuso la finestra, apre il monitor nativo con quel processo selezionato, consentendone la terminazione. Un piccolo indicatore interno all'icona segnala lo stato attivo, senza colori aggiuntivi.

### 12.2 Superfici client

Ogni finestra ha una superficie privata del kernel nella REU. L'app può disegnarvi attraverso syscall, ma non conosce un puntatore scrivibile alla superficie.

**Il mapping diretto del framebuffer userspace è rinviato.** Per disegno personalizzato l'app può allocare un array lineare di pixel INDEX8 nella propria arena e inviarlo con BLIT8. Questo array è una sorgente: modificarlo non aggiorna automaticamente lo schermo. Il kernel effettua conversione, clipping e composizione; pagina-colonne, nibble e timing UPIC restano privati. L'estensione futura dovrà preservare questa separazione.

Formato interno iniziale: tile 8×8, 4 bpp, 32 byte per tile; tile ordinate per righe. Dentro una tile usare quattro colonne packed da otto byte, con pixel pari nel nibble basso:

```text
tile_x = x >> 3; tile_y = y >> 3
tile_cols = ceil(client_width / 8)
tile_offset = (tile_y * tile_cols + tile_x) * 32
byte_offset = ((x & 7) >> 1) * 8 + (y & 7)
```

Queste tile sono soltanto il formato di memorizzazione grafica: **non cambiano le celle 32×32 del desktop**.

Con una finestra 320×200 e bordi/titolo definiti sopra, il client massimo è 316×184: 40×23 tile, 29.440 byte. Entra in uno slot da 32 KiB.

All'apertura inizializzare tutta la parte utilizzata della superficie prima di esporla; fino a quel momento la shell può mostrare il chrome e un client uniforme. La creazione è un lavoro limitato, non un unico DMA lungo.

### 12.3 Dirty regions

Un solo framebuffer locale. Non creare un secondo framebuffer locale o ricopiare l'intero schermo ogni frame.

Conservare fino a 16 rettangoli sporchi. Unire quelli sovrapposti; se la capacità viene superata, passare a una ricomposizione completa **progressiva e limitata**, non a un lavoro monolitico.

Per ogni area sporca:

1. Ricostruire sfondo, icone/widget e finestre secondo l'ordine Z corrente.
2. Disegnare il chrome con primitive native locali.
3. Leggere soltanto le porzioni client visibili necessarie.
4. Clippare rispetto a schermo, client e finestre davanti.
5. Aggiornare il framebuffer in pezzi limitati durante il tempo ammesso.

Il contenuto di una finestra può essere ripristinato anche quando l'app è bloccata, perché la sua superficie appartiene al kernel. Una finestra coperta continua ad aggiornare la propria superficie senza costringere il compositor a disegnarla.

Non promettere presentazione atomica di un intero frame senza doppio buffer. Gli aggiornamenti grandi possono apparire progressivamente; le operazioni piccole della UI devono avere precedenza e latenza limitata.

### 12.4 Cursore

Cursore software in palette shell, con piccolo save-under locale. Prima di disegnare un'area che lo interseca, ripristinare il fondo; dopo gli aggiornamenti, salvare il nuovo fondo e ridisegnare il cursore.

Il save-under deve includere l'allineamento a coppie di pixel: 12 pixel di larghezza con X dispari possono occupare 7 byte per riga. La riserva da 128 byte copre 7×16=112 byte.

Non usare automaticamente sprite VIC per il cursore: verificare prima la compatibilità con il modo border UPIC. Il primo backend usa soltanto il framebuffer software.

## 13 Input ed eventi

### 13.1 Backend iniziali

Tastiera C64 completamente utilizzabile dal primo MVP. Puntatore iniziale da joystick in porta 2 o backend mouse disponibile e verificato sull'Ultimate; non dipendere da un nuovo stack USB.

Il driver espone eventi normalizzati, indipendenti dal dispositivo. Un futuro 1351/backend mouse deve poter essere aggiunto senza cambiare VM e window manager.

Scorciatoie iniziali:

| Comando | Azione |
|---|---|
| F1 | Mostra desktop / ripristina finestre |
| F3 | Prossima finestra |
| F5 / F6 (Shift+F5 fisico) | Prossimo / precedente oggetto desktop o controllo client |
| RETURN | Attiva il controllo selezionato |
| RUN/STOP | Annulla menu, drag o modalità di spostamento |
| C=+M sul desktop | Sposta l'oggetto selezionato per celle |
| C=+RUN/STOP | Terminazione forzata dell'app attiva tramite shell |

Non basare la navigazione su un tasto Tab fisico non presente nella tastiera standard. Le combinazioni devono essere verificate sul driver reale.

La shell consuma F1, F3 e le proprie combinazioni prima di generare eventi per le app. Sul desktop o nei pannelli nativi gestisce anche la navigazione; nella finestra client F5/F6, RETURN e RUN/STOP sono normali eventi che la libreria controlli interpreta. Keycode, ASCII, modificatori e flag sono congelati nell'allegato SDK §2.1, senza una tabella per-app nel manifest.

### 13.2 Code

Ogni app ha una coda di otto eventi da 16 byte:

| Offset | Campo |
|---|---|
| 0 | tipo, u8 |
| 1 | flag, u8 |
| 2 | handle finestra, u16 |
| 4 | arg0, i16 |
| 6 | arg1, i16 |
| 8 | arg2, u16 |
| 10 | frame di origine, u32 |
| 14 | riservato, due byte zero |

Tipi iniziali: POINTER_MOVE, BUTTON_DOWN, BUTTON_UP, KEY_DOWN, KEY_UP, FOCUS, BLUR, CLOSE_REQUEST e INPUT_RESET. Le coordinate puntatore sono relative al client; i tasti hanno un codice normalizzato e un eventuale ASCII.

Coalescere POINTER_MOVE. Se non è possibile accodare una transizione, scartare gli eventi di input ormai incoerenti e marcare INPUT_RESET in un flag pendente esterno al ring. Alla consegna l'app cancella il proprio stato dei tasti mantenuti e legge pulsanti/modificatori/puntatore tramite INPUT_STATE; non si promette una bitmap dei tasti premuti. La prossima KEY_DOWN ricrea lo stato del relativo tasto. Il flag viene consegnato prima di nuovi eventi di input, senza rischiare di perderlo per overflow.

Le notifiche critiche hanno flag pendenti separati dal ring: CLOSE_REQUEST persistente fino alla consegna, e stato finale di focus da notificare. Cambi ripetuti prima della lettura possono coalescere nell'ultimo FOCUS/BLUR; non richiedono una seconda coda. Ordine di consegna: CLOSE_REQUEST, variazione focus, INPUT_RESET, ring ordinario. A ogni perdita di focus invalidare gli eventi di input della vecchia destinazione e la sua cattura, e marcare INPUT_RESET anche se un successivo FOCUS assorbe il BLUR pendente. BLUR cancella anche lo stato logico dei tasti/pulsanti dell'app. Una nuova finestra parte con coda e flag puliti.

La tastiera va alla finestra attiva, dopo i comandi globali della shell. Il drag del desktop e quello delle finestre usano cattura del puntatore nel kernel e non dipendono dalle code delle app. Un BUTTON_DOWN dentro un client gli assegna cattura implicita fino all'ultimo BUTTON_UP, BLUR, nascondimento o chiusura. Durante la cattura inviare anche movimento/rilascio fuori client, con coordinate signed; senza cattura gli eventi puntatore vanno solo al client visibile sotto il puntatore. Un click sul client ne acquisisce prima il focus.

## 14 ABI delle syscall

### 14.1 Convenzioni

SYSCALL usa l'ID in b1. Argomenti in R/P, senza puntatori nativi. R0 ritorna lo stato; gli altri registri restano invariati salvo output espliciti.

Stati: 0 OK, 1 EINVAL, 2 ERANGE, 3 ENOMEM, 4 EAGAIN, 5 EBADF, 6 ENOSYS, 7 ECANCELLED, 8 EIO, 9 EBUSY, 10 ENODEV, 11 ENOTSUP, 12 ETIMEDOUT, 13 ENOENT, 14 EEXIST, 15 EACCES, 16 ENOSPC, 17 EOVERFLOW, 18 ENOTDIR, 19 EISDIR, 20 ESTALE, 21 EROFS, 22 EDOM, 23 EDIVZERO. ENOSYS indica ID sconosciuto; ENOTSUP un'operazione conosciuta ma non supportata dal profilo. EOVERFLOW include gli elenchi che superano i limiti dichiarati; ESTALE identifica riferimenti a una generazione superata. EDOM/EDIVZERO sono gli errori numerici descritti in NUMERICS.md.

Gli errori di argomento delle syscall restituiscono uno stato senza modifiche parziali evitabili. Gli accessi illegali delle istruzioni VM generano invece fault del processo. Validare tutti gli intervalli, anche quelli contenuti in descrittori o array di comandi.

Le syscall bloccanti mantengono il processo in WAIT_JOB/WAIT_EVENT/SLEEPING; la CPU continua con gli altri processi. “Bloccante per l'app” non significa “bloccante per il sistema”.

### 14.2 Servizi iniziali

| ID | Nome | Input | Output/comportamento |
|---|---|---|---|
| 00 | PROC_EXIT | R0=exit code | Termina; non ritorna |
| 01 | SYS_INFO | — | R1=ABI, R2=320, R3=200, R4=0 riservato; capability in UltimateInfo |
| 02 | GET_FRAME | — | R1=low16, R2=high16 del contatore frame |
| 03 | SLEEP | R0=numero frame | 0 equivale a YIELD; altrimenti attesa |
| 04 | EVENT_WAIT | P0=record destinazione, R0=timeout, R1=Window | 0 poll; $FFFF attesa indefinita; altrimenti frame |
| 05 | WIN_CREATE | P0=descrittore | R1=handle; una finestra per app |
| 06 | WIN_CLOSE | R0=handle | Chiude la finestra, non necessariamente il processo |
| 07 | WIN_TITLE | R0=handle, P0=testo, R1=lunghezza | Massimo 15 caratteri |
| 08 | GFX_SUBMIT | R0=handle, P0=comandi, R1=numero | 1–16 comandi; ritorna quando la superficie è aggiornata |
| 09 | GFX_PRESENT | R0=handle | Attende la presentazione del lavoro già accettato |
| 0A | MEM_FILL | P0=dst, R1=byte, R2/R3=lunghezza | Riempimento in pezzi limitati |
| 0B | MEM_COPY | P0=dst, P1=src, R2/R3=lunghezza | Semantica memmove, overlap incluso |
| 0C | MEM_INFO | — | P0/P1=heap first/last, P2/P3=stack first/last |
| 0D | INPUT_STATE | R0=Window | R1=pulsanti, R2=modificatori, R3=x, R4=y client signed; binding InputState nell'SDK |

Lunghezza a 32 bit = R2 + (R3 << 16), da validare contro lo spazio reale; non troncarla a 16/24 bit prima dei controlli. MEM_FILL/MEM_COPY con lunghezza zero non accedono ai puntatori.

EVENT_WAIT valida proprietà e validità di R1 prima di leggere la coda o sospendere il processo; un handle scaduto dà EBADF anche se ora esiste un'altra finestra dello stesso processo. Restituisce EAGAIN se il timeout scade; in questo caso non altera il record. Scrive il record solo dopo aver validato e reso disponibili tutti i suoi byte. INPUT_STATE verifica lo stesso handle, senza consumare eventi; le coordinate possono essere fuori client. R1 è zero senza cattura della finestra, R2 è zero senza focus: non ricreare pressioni il cui rilascio non verrebbe consegnato. Per le syscall core, gli output scalari dichiarati sono zero su errore; i buffer restano invariati salvo errori di esecuzione successivi alla validazione di lavori progressivi. Su errore di argomento nessun pezzo viene eseguito.

GET_FRAME è un contatore monotono modulo 2^32, incrementato a ogni periodo video PAL, anche senza ricomposizione del desktop. Timeout e uptime usano differenze unsigned del contatore, senza dipendere dall'RTC o dall'orologio civile; nessun timeout finito dell'MVP si avvicina a 2^31 frame.

Handle finestra: identificatore non nullo a 16 bit, verificato contro processo proprietario e finestra viva. Usa il contatore monotono per incarnazione del processo definito in ULTIMATE-API.md §3: niente riuso mentre quella app è viva; esaurimento = ENOSPC confinato al proprietario. Riavviare il contatore solo dopo cleanup completo e nuova inizializzazione dell'app.

### 14.3 Creazione finestra

Descrittore WIN_CREATE, 16 byte:

| Offset | Campo |
|---|---|
| 0 | x, u16 |
| 2 | y, u16 |
| 4 | larghezza esterna, u16 |
| 6 | altezza esterna, u16 |
| 8 | puntatore titolo, u24 |
| 11 | lunghezza titolo, u8, massimo 15 |
| 12 | flag, zero per l'MVP |
| 13 | riservato, tre byte zero |

Dimensioni e posizione devono entrare nello schermo e rispettare i minimi. X deve essere pari nel backend iniziale. Input non valido restituisce EINVAL/ERANGE; non correggere silenziosamente una struttura malformata.

### 14.4 Comandi grafici

Record di 16 byte:

| Offset | Campo |
|---|---|
| 0 | operazione, u8 |
| 1 | flag, u8 |
| 2 | x, i16, coordinate client |
| 4 | y, i16 |
| 6 | w oppure lunghezza testo, u16 |
| 8 | h, u16 |
| 10 | colore primo piano, u8, 0–15 |
| 11 | colore fondo, u8, 0–15 |
| 12 | puntatore sorgente, u24 |
| 15 | riservato, zero |

Operazioni: 1 CLEAR, 2 FILL_RECT, 3 FRAME_RECT, 4 TEXT, 5 BLIT4, 6 BLIT8.

- CLEAR usa il primo piano per l'intero client.
- FILL_RECT riempie il rettangolo clippato.
- FRAME_RECT disegna il bordo interno di un pixel del rettangolo originale e poi lo clippa; non crea bordi nuovi lungo il limite del client.
- TEXT usa w come numero di byte ASCII, massimo 255; h=0. Flag bit 0 indica fondo trasparente; altrimenti usa il colore fondo. Nessuna ricerca illimitata del terminatore.
- BLIT4 legge una sorgente row-major, stride ceil(w/2), due pixel per byte, primo pixel nel nibble basso. Verificare l'intero intervallo sorgente con aritmetica larga. Niente scaling o alpha nell'MVP.
- BLIT8 legge una sorgente row-major, stride=w, un byte per pixel. I quattro bit bassi selezionano l'indice 0–15; i quattro bit alti sono ignorati. Non è necessario scansionare tutti i pixel per validare il batch. Il controllo del buffer usa w×h con aritmetica a 32 bit e verifica l'intero intervallo prima degli effetti.

Gli altri flag e i campi inutilizzati devono essere zero: CLEAR usa solo primo piano; FILL_RECT/FRAME_RECT usano x/y/w/h e primo piano; TEXT usa x/y/w, i due colori e sorgente; BLIT4/8 usano x/y/w/h e sorgente. Dimensioni nulle dei rettangoli o testo di lunghezza zero sono no-op; colori e formato vanno comunque validati. Non dereferenziare la sorgente dei comandi vuoti. Il clipping di un comando non vuoto non evita la validazione dell'intero intervallo sorgente dichiarato.

Validare il batch prima degli effetti. Durante il lavoro l'app è sospesa, quindi comandi e sorgenti restano stabili. Elaborare per tile/porzioni limitate, con continuazioni esplicite.

GFX_SUBMIT aggiorna la superficie e marca il danno; non garantisce che tutto sia già sul monitor. GFX_PRESENT attende che le parti attualmente visibili siano composte e attraversate da uno scanout. Se la finestra è interamente nascosta, può terminare quando la superficie è aggiornata. Il ripristino successivo userà quella superficie.

Una continuazione del compositor non può riusare geometria o ordine Z ormai superati. Mantenere una generazione della scena per move/focus/show/hide/close e una revisione del contenuto per finestra. Prima di pubblicare un pezzo preparato, verificare entrambe: se sono cambiate, scartare lo staging obsoleto e ricomporre dalla scena corrente. Cancellare il danno solo per la revisione effettivamente composta. GFX_PRESENT attende almeno la revisione richiesta, senza cancellare danno aggiunto nel frattempo.

### 14.5 Servizi estesi

L'allegato [SDK e servizi Ultimate](ULTIMATE-API.md) riserva gli ID 20–2F per file/directory, 40–4F per SID, 50–5F per Ultimate Audio, 60–6F per video e 70–7F per informazioni Ultimate, storage e RTC. 80–8F e 90–9F sono riservati alle future rete e HTTP e restituiscono ENOSYS nell'MVP. Tutti gli ID sono esadecimali. Usa le stesse regole di isolamento, fuel, continuazione e controllo degli argomenti; nessuna API esegue un puntatore nativo fornito dall'app.

L'ID **30 NUM_OP** è definito in [NUMERICS.md](NUMERICS.md): selettore in R1, operandi scalari in R2/R3 e R4/R5, risultato in R2/R3, stato in R0. È un servizio numerico del kernel, senza dipendenza da UCI o dalle capability hardware Ultimate. 31–3F restano ENOSYS.

## 15 Boot e strumenti di sviluppo

### 15.1 Bootstrap

Produrre un PRG piccolo e un'immagine REU da 16.777.216 byte. Il PRG parte all'indirizzo convenzionale $0801 e carica dalla REU i segmenti residenti, con destinazioni esplicitamente consentite.

Il pack REU deve essere già caricato all'avvio del PRG: la consegna include la procedura verificata di caricamento nell'emulatore e nel menu Ultimate. Un loader del pack tramite il servizio file del nuovo OS non è richiesto per il primo bootstrap; questo servizio esiste soltanto dopo l'avvio del kernel.

Non creare un PRG piatto che venga caricato ingenuamente attraverso $D000–$DFFF con I/O attivo. Il bootstrap non deve sovrascriversi mentre copia i segmenti; la RAM della sua area può diventare cache solo dopo il salto definitivo al kernel.

Procedura:

1. Disabilitare gli interrupt non necessari e impostare un ambiente 6510 noto, incluso CLD.
2. Verificare header/build del pack REU.
3. Verificare presenza e dimensione della REU con una prova che salva e ripristina i byte interessati; un test di alias deve distinguere almeno le dimensioni inferiori supportate.
4. Verificare PAL e velocità effettiva; attendere la fine dell'eventuale fase lenta dopo reset.
5. Caricare soltanto i segmenti residenti autorizzati e inizializzare vettori, RAM e framebuffer.
6. Inizializzare cache, processi, input, superfici e desktop; predisporre le richieste incrementali di scoperta storage e RTC, che proseguono a display avviato nelle finestre di servizio fuori dalle 200 righe attive.
7. Avviare il raster e il ciclo del kernel.

Una configurazione insufficiente produce una diagnostica leggibile; non tentare di eseguire il renderer 64 MHz a una velocità minore fingendo compatibilità.

### 15.2 Pack MVP

Header REU di 16 byte a $000000:

| Offset | Campo |
|---|---|
| 0 | Otto byte ASCII: COSREU01 |
| 8 | build_tag, u32 little endian |
| 12 | versione ABI, u16 |
| 14 | numero app, u8, 0–4 |
| 15 | riservato, zero |

Il medesimo build_tag viene compilato nel bootstrap. Serve a rilevare un PRG abbinato al pack sbagliato, non è una firma di sicurezza.

Nell'MVP il bundler genera i descrittori e gli indirizzi come costanti assembly, oltre a un manifest JSON leggibile. Non serve un linker dinamico o un formato di eseguibile generale sul C64.

Per ogni app dichiarare ID stabile, nome, sorgente, arena, sezioni codice/dati/BSS/heap/stack, entry point e seed per i dati inizializzati. ID distinti in 1…65535, nomi ASCII di 1…15 byte; il PID esposto alla VM è l'ID stabile dell'app, non l'indice dello slot PCB. Il codice ha lunghezza positiva multipla di quattro. Le arene non si sovrappongono; il build valida tutti i limiti, gli allineamenti di §6.3 e gli indirizzi di branch statici. heap_min e stack_size sono multipli di 128 e almeno 128; anche un pack senza app è valido.

Il manifest di ingresso al bundler può restare piccolo. Esempio di pack con una sola app, con numeri decimali per evitare un formato JSON non standard:

```json
{
  "format": "COSPACK1",
  "abi": 1,
  "numeric_profile": "COS-NUM-1",
  "target": "c64u-pal-upic320",
  "storage": { "mode": "discover", "directory": "cos", "marker": ".cos-volume" },
  "apps": [
    {
      "id": 1,
      "name": "Note",
      "object": "build/note.cobj",
      "arena_start": 262144,
      "arena_size": 1048576,
      "stack_size": 16384,
      "heap_min": 131072
    }
  ]
}
```

La modalità discover cerca l'albero dati predisposto sui supporti rilevati, secondo ULTIMATE-API.md §5.4. È ammessa in alternativa `"storage": {"mode": "explicit", "root": "/usb0/cos"}` per una configurazione nota; quel path non è garantito su ogni dispositivo. Il bundler rifiuta configurazioni ambigue e produce anche il marker `COSDATA1\n` e l'albero `cos/.system`, `cos/apps/<id>` da installare. Una root assente non impedisce il boot in RAM; una scelta fra più candidati avviene dalla shell dopo l'avvio del desktop.

I path host sono relativi alla root C-OS dichiarata al bundler. Codice/dati/BSS vengono collocati in ordine, con allineamento di 128 byte; stack in cima all'arena; spazio rimanente all'heap, almeno heap_min. Il report espone tutti gli intervalli effettivi e il seed dei dati. L'entry viene dal simbolo esportato `_cos_start` per le app C-Script, oppure dall'entry dichiarata nell'oggetto assembler.

All'ingresso dell'app: PC=entry, SP=stack_last, R0=PID, R1=versione ABI, gli altri R=0; P0=heap_first, P1=heap_last, P2=inizio dati, P3=stack_last. Se i dati inizializzati sono vuoti, P2 vale zero; indirizzi BSS e dei dati runtime vengono dal linker. Il linker e la libreria iniziale devono usare questa stessa convenzione.

### 15.3 Toolchain

Assembly nativo: Kick Assembler, coerente con il workspace. **Rust è la scelta consigliata per il compilatore e il tooling host**: assembler/disassembler VM, bundler, reference VM e runner. Iniziare con un piccolo workspace Cargo e condividere definizioni ISA, formati e diagnostica fra i comandi; non introdurre molti crate o framework prima che servano. Preferire la libreria standard e poche dipendenze motivate, con Cargo.lock e toolchain documentata per build riproducibili. Rust gira sul computer di sviluppo; kernel e interprete target restano assembly 6510.

Script ausiliari già presenti e oracoli indipendenti, per esempio calcoli razionali esatti per i test numerici, possono usare Python quando utile. Non mantenere due compilatori o due pipeline di packaging equivalenti. I comandi Cargo/CLI proposti in LANGUAGE.md sostituiscono la precedente indicazione di costruire tutta la toolchain in Python.

Fornire:

- assembler del bytecode a due passate, etichette, costanti e listing;
- compilatore C-Script descritto in LANGUAGE.md, binding SDK tipizzati ed esempi sorgente;
- disassembler che mostri indirizzi, opcode e operandi;
- bundler PRG/REU, manifest e map file;
- interprete di riferimento host per l'ISA;
- runner di test per emulatore e acquisizione dei contatori;
- una libreria userspace minima per chiamate, heap e controlli di base.

Verificare ISA, memoria e scheduler con piccoli programmi assembler, poi completare C-Script nella stessa versione MVP. Non serve portare un compilatore C o Lua. Il formato resta sperimentale fino al completamento dei test fondamentali; eventuali cambi devono aggiornare insieme compilatore, assembler, runtime, ABI e test.

## 16 Diagnostica e prestazioni

Contatori minimi, leggibili senza alterare il normale flusso dell'app:

- frame prodotti e sincronizzazioni mancate;
- deadline miss e DMA rinviati;
- opcode ritirati e context switch per processo;
- miss della cache codice/dati, write-back e byte trasferiti;
- massimo tempo di un pezzo nativo e massimo trasferimento DMA;
- profondità massima dello stack hardware;
- overflow/coalescing delle code eventi;
- rettangoli/tile ricomposti e backlog grafico;
- frame di ricezione input, applicazione dell'effetto e prima visualizzazione;
- richieste UCI, timeout, byte I/O, canali audio attivi e campioni protetti;
- durata delle scansioni directory/storage, occupazione delle snapshot, generazioni storage e anzianità della cache RTC.
- chiamate e tempo nativo NUM_OP per processo, formato e operazione; nelle build diagnostiche, conteggi per funzione/helper e costo delle conversioni testuali.

Contatori estesi e trace possono essere abilitati nella build diagnostica. La build ordinaria non deve registrare una riga di log per opcode.

Misurare separatamente interprete, miss/cache, DMA, disegno, composizione, attesa del raster e latenza dell'interazione. Non usare il numero di aggiornamenti parziali come FPS completi.

Obiettivi iniziali da verificare:

| Scenario | Obiettivo |
|---|---|
| Desktop fermo | Nessuna ricomposizione completa ripetuta; scanout regolare |
| Input sulla shell con due app di stress | Latenza visibile p95 entro 2 frame, p99 entro 3 frame |
| Movimento del puntatore | Aggiornamento quando ci sono input; niente dipendenza dai yield delle app |
| App in loop infinito | Le altre app e la shell continuano a progredire |
| Grande MEM_COPY/FILL | Servizio progressivo senza monopolizzare un frame o una coda |
| Stabilità video | Zero deadline miss in 10 minuti del carico di accettazione qualificato |
| Avvio/apertura finestre | Misurare e riportare; distinguere chrome pronto e superficie client pronta |

A PAL, due/tre frame sono circa 40/60 ms. Sono obiettivi di accettazione da misurare; non risultati già ottenuti e non garanzie per qualsiasi carico immaginabile.

Se la latenza non rientra, profilare prima di aggiungere complessità. Priorità di intervento: ridurre lavoro inutile, migliorare località, ridurre syscall troppo fini, tarare i pezzi nativi; solo dopo valutare nuove politiche del dispatcher o uso dei margini orizzontali.

## 17 Test di accettazione

### 17.1 Memoria e ISA

- Letture/scritture a 8, 16 e 24 bit, allineate e non allineate.
- Attraversamento di linea cache e confine $xxFFFF/$yy0000.
- LD8 all'ultimo byte REU valido; rifiuto di un accesso multibyte che oltrepassa $FFFFFF.
- Protezione della riserva kernel, delle altre arene e del codice.
- Overflow/underflow dei puntatori, senza wrap silenzioso.
- Branch presi/non presi, signed/unsigned, PC fuori codice o non allineato.
- Chiamate annidate e salvataggio del PC a 24 bit.
- Stack pieno/vuoto e SETSP fuori limiti.
- STORE/PUSH/CALL con miss: un solo effetto e una sola contabilizzazione.
- Opcode e campi riservati malformati: fault confinato all'app.
- Manifest con sezioni dati/BSS vuote; rifiuto di arene disallineate, ID duplicati e heap/stack vuoti; pack con zero app avviabile.

### 17.2 Fuel e ripresa

Con quantum di test piccolo, per esempio tre istruzioni, confrontare gli stati host e 6510 dopo ogni slice. Il conteggio riguarda istruzioni ritirate, non tentativi di fetch.

Eseguire loop senza syscall e senza yield; verificare preemption e progresso degli altri processi. Ripetere con miss continui, dirty eviction, attese di eventi e copie native lunghe.

Un processo non deve ottenere quantum gratuiti per cache miss o lavori CPU nativi. Una syscall sospesa non deve essere eseguita due volte. Verificare progresso simultaneo di una coda VM sempre piena e una coda nativa sempre piena, anche attraverso scadenze raster. Il caricamento dei registri del processo successivo deve essere indipendente dallo stato lasciato dal precedente.

### 17.3 REU e coerenza

Verificare zero-length, overlap avanti/indietro, byte finali, annullamento di un lavoro, write-back seguito da lettura nativa, scrittura nativa seguita da LOAD VM e riutilizzo dello slot del processo.

Confrontare checksum e contenuti attesi. Un test che controlla soltanto i registri scritti al DMA non dimostra la correttezza dei dati restituiti.

Verificare anche le scritture VM e native verso campioni audio protetti, la visibilità delle ultime STORE prima di PLAY e la cessazione delle letture hardware prima di liberare/riusare il campione.

### 17.4 UI

- Raster reale 320×200 e tutti i pixel di bordo presenti.
- Pixel della shell limitati agli indici 0, 1, 11, 12, 15.
- Cella 32×32: tutte le 60 posizioni valide, margini corretti.
- Spostamento di app e widget fra celle, anche non adiacenti.
- Cella occupata, drop fuori area, annullamento, tastiera e drag veloce.
- Nessuna posizione desktop intermedia a passi di 8 pixel.
- Focus, ordine Z, “Mostra desktop”, ripristino e chiusura.
- Ripristino di una finestra la cui app non risponde.
- Cursore su bordi, X dispari e regioni ridisegnate, senza scie.
- Overflow degli eventi senza pulsanti/tasti logicamente bloccati.
- Perdita/riacquisto rapido del focus, reset fuori dal ring, rilascio del puntatore fuori client e handle scaduti senza consumo di eventi della nuova finestra.
- Desktop interamente usabile da tastiera, con 0–4 launcher; selezione di un processo vivo senza finestra tramite il monitor.
- Memoria della superficie e clipping con coordinate negative e rettangoli parzialmente visibili.
- Batch grafico con campi inutilizzati nonzero respinto con EINVAL prima di ogni effetto; FRAME_RECT clippato senza bordi artificiali.
- INPUT_STATE dopo BLUR durante una pressione non riattiva pulsanti della vecchia finestra; rilascio fuori client e successivo focus restano coerenti.

Il controllo della palette va eseguito sugli indici del framebuffer, non contando gli RGB di una fotografia o del PNG del mockup.

### 17.5 Carico integrato

Per almeno dieci minuti:

1. App A in loop aritmetico infinito.
2. App B con letture/scritture oltre 64 KiB e miss ripetuti.
3. App C che aggiorna piccoli rettangoli.
4. Input continuo sulla shell: puntatore, spostamenti di icone, cambio focus e finestre.
5. Inserimento di fault e terminazione forzata di un'app.
6. Controllo di frame, latenza, memoria, avanzamento dei processi e correttezza dei dati.

Conservare configurazione, hash degli artefatti, manifest, map, output numerici e acquisizioni. Indicare separatamente risultati dell'emulatore e del dispositivo fisico.

### 17.6 Linguaggio e SDK

Superare i test descritti negli allegati: esempi C-Script compilabili, indici oltre 64 KiB, aritmetica intera 16/32 bit e float24/float32, errori di tipo e bounds; due app che usano file differenti senza contaminarsi; directory/stat e mutazioni entro root; storage assente/scollegato e generazioni superate; cache RTC valida/scaduta con scheduling monotono; timeout UCI senza blocco del raster; pulizia SID/PCM alla terminazione; BLIT8 coerente con l'array sorgente. Ripetere il carico integrato con letture/scritture file, scansioni directory, calcolo float senza yield e riproduzione PCM in corso.

## 18 Sequenza di implementazione

| Fase | Consegna | Condizione di completamento |
|---|---|---|
| M0 Hardware e budget | Probe turbo/REU, renderer 320, map file, misure DMA e primo bilancio residente | Geometria verificata nel backend disponibile; timing esplicito; ingombri misurati distinti dalle riserve stimate |
| M1 VM host | ISA, assembler, disassembler, reference VM | Test semantici e generazione di app minime |
| M2 VM 6510 | Dispatcher, puntatori, cache e stack | Confronto degli stati con il reference su confini e miss; budget cumulativo aggiornato prima di ampliare SDK/UI |
| M3 Scheduler | Fuel, PCB, attese e lavori REU limitati | Due loop senza yield convivono con il raster |
| M4a C-Script | Compilatore host, libreria minima, ABI di chiamata e source map | Esempi e test del linguaggio eseguiti sulla VM; loop senza yield preemptibili |
| M4b Numeri frazionari | Float24/float32, NUM_OP, conversioni numeriche/testuali e modello host | Corpus bit-exact, isolamento scratch, budget e timing dei due formati verificati |
| M5 Grafica e input | Primitive, superfici, BLIT8, compositor, cursore ed eventi | Clipping, coerenza, ripristino e input verificati |
| M6a Storage e tempo | UCI incrementale, file/directory/stat, mutazioni, scoperta storage, RTC e binding | Concorrenza I/O, snapshot, scollegamento, timeout e cache del clock verificati |
| M6b Audio Ultimate | SID, PCM e binding C-Script | Lease, coerenza campioni e cleanup verificati; budget completo RAM/REU aggiornato |
| M7 Desktop e app | Stile C, griglia 32×32, persistenza ed esempi in C-Script | Interazione completa con carico concorrente |
| M8 Qualificazione MVP | Stress, profili e documentazione riproducibile | Criteri di accettazione misurati, limiti residui dichiarati |

La numerazione identifica le consegne, non impone una catena artificiale: M1 può procedere mentre si qualifica M0; M2 integra modello host e vincoli hardware, poi M3 verifica lo scheduling. Dopo M3, M4a e i servizi M5/M6a/M6b possono avanzare con piccoli programmi assembler di prova; M4a aggiunge progressivamente i binding. M4b usa M4a/M3, ma **non blocca M5 né una prima demo del desktop**. M7 integra gradualmente questi rami; M8 richiede tutte le consegne, compresi entrambi i float e i servizi previsti. Evitare stub permissivi che facciano apparire completato un servizio mancante.

Il budget residente è un gate continuo, non una verifica da rimandare a M6b. Già in M0/M2 riportare separatamente codice assemblato, tabelle, ZP, stack/scratch, cache e riserve per moduli ancora da realizzare; includere appena disponibile un candidato numerico assemblato. L'obiettivo di 4 KiB per i due float è parte del budget nativo esistente, non memoria aggiuntiva. Una stima non prova che tutto entrerà: ogni milestone aggiorna la mappa e segnala subito un superamento. Prima di ampliare la UI risolvere gli sforamenti già misurati riducendo codice o rivedendo motivatamente il layout; overlay, nuovi scheduler e formati alternativi non sono prerequisiti da costruire preventivamente.

Le estensioni N1 (TCP/UDP) e N2 (HTTP/JSON) sono successive a M8. Entrambe riusano il motore UCI; HTTP delegato al firmware non richiede prima uno stack HTTP userspace su TCP. I loro gate e contratti preliminari sono nell'allegato SDK §10.

Avanzare per risultati eseguibili. Non costruire prima un grande SDK o un desktop completo sopra una VM non verificata.

Se il C64 Ultimate fisico non è disponibile, completare le verifiche emulabili e consegnare una procedura hardware precisa. Lo stato finale deve distinguere “MVP verificato in emulazione” da “timing qualificato su hardware”; non attendere indefinitamente un dispositivo e non inventare la qualificazione.

## 19 Parametri da decidere tramite misure

| Parametro | Valore iniziale | Motivo per cambiarlo |
|---|---|---|
| Quantum VM | 128 opcode | Overhead di switch o latenza |
| Linea cache | 128 byte | Rapporto setup DMA/località |
| Cache codice | 2 linee per processo | Miss e traffico del codice |
| Cache dati | 8 linee globali | Thrashing fra heap e stack |
| DMA ordinario | Fino a 128 byte | Limiti temporali misurati |
| Guard time | Almeno il margine qualificato, prova iniziale di 2 righe | Worst case reale e fase del renderer |
| Dirty list | 16 rettangoli | RAM disponibile e frequenza di overflow |
| Event queue | 8 eventi per app | Overflow e costo di servizio |
| Snapshot directory | 2 × 16 KiB REU, massimo 256 voci ciascuna | Dimensione dei nomi, limiti delle directory e riserva REU |
| Elenco storage | Massimo 5 supporti | Profili hardware qualificati |
| Cache RTC | Refresh ogni 50 frame, scadenza dopo 100 | Carico UCI e qualità del dato disponibile |
| Nucleo numerico | Obiettivo ≤4 KiB residente per entrambi i formati, bridge e cast numerici | Dimensione reale, ZP/scratch, costi REU e vantaggio float24/float32 |
| Finestra nativa residente | Mappa proposta | Dimensione del codice effettivamente assemblato |

Non sono parametri da cambiare per nascondere un problema: palette della shell, griglia a celle intere, protezione fra app, indirizzi oltre 64 KiB, preemption obbligatoria e proprietà esclusiva del video/REU da parte del kernel.

## 20 Evoluzioni successive

Dopo l'MVP:

- ridimensionamento delle finestre e più controlli;
- mapping di un framebuffer logico lineare per il userspace, con acquire/present/release e coerenza esplicita;
- evoluzioni di C-Script solo quando richieste da app reali;
- eventuale float16, fixed point e funzioni matematiche avanzate, con misure e contratti espliciti;
- loader di pacchetti, allocazione dinamica delle arene e più app installate;
- widget userspace con gli stessi limiti delle app;
- uso qualificato dei margini orizzontali per lavori nativi;
- formato di bytecode più compatto, superistruzioni o fuel per blocchi, soltanto se il profiling li giustifica;
- eventuale framebuffer più compatto, senza perdere il controllo del timing;
- N1: client TCP/UDP con timeout, handle e verifica della latenza imposta agli altri servizi UCI;
- N2: HTTP/JSON nel firmware, con gestione degli handle e verifica separata di HTTPS;
- fullscreen dedicato, palette, streaming audio avanzato, file picker e gestione di immagini disco/SoftIEC.

Queste estensioni non devono diventare prerequisiti della prima versione.

## 21 Progetti di riferimento

I progetti studiati sono fonti di idee, non dipendenze obbligatorie:

| Progetto | Spunto da esaminare |
|---|---|
| [Acheron](https://www.white-flame.com/acheron/) | Registri virtuali, dispatcher piccolo, punti di trap |
| [BBC VM e compilatore](https://github.com/TheEnbyperor/bbc-c) | Toolchain host e VM su 6502 con memoria estesa |
| [semu-c64](https://github.com/onnokort/semu-c64) | Accesso alla REU e stato di una CPU emulata; evitare il costo di un'intera macchina RISC-V per il nostro ABI |
| [Hopper](https://github.com/sillycowvalley/Hopper) | Separazione runtime/linguaggio e organizzazione del bytecode; verificare le dipendenze da 65C02 |
| [ChibiVM](https://www.chibiakumas.com/chibivm/) | Istruzioni e portabilità dell'interprete |
| [6o6](https://github.com/classilla/6o6) | Separazione fra esecuzione virtuale e backend della memoria |
| [PLASMA](https://github.com/dschmenk/PLASMA) | Ambiente e compilazione per macchine 6502 |
| [EightBall](https://github.com/bobbimanners/EightBall) | Linguaggio e VM compatti su C64 |
| [SWEET16 per C64](https://github.com/Silverune/Sweet16) | Dimensione minima e aritmetica virtuale a registri |
| [QuakeC originale](https://github.com/id-Software/Quake-Tools/tree/master/qcc) | Tabella operatori/tipi, contratto condiviso compiler/runtime e profiling; analisi in NUMERICS.md |
| [XC-BASIC](https://github.com/neilsf/xc-basic3) e [LLVM-MOS](https://github.com/llvm-mos/llvm-mos/tree/main/compiler-rt/lib/builtins/mos) | Float software e convivenza con tipi interi; confronto dei candidati in NUMERICS.md |

Lua e WAMR non sono runtime del primo MVP. C-Script compila verso C-OS; cambiare allocatore a un interprete esistente non basta a rendere lineare la REU.

Riferimenti nel workspace C64 originale, esterni a questa repository:

- Renderer UPIC di riferimento: `poc/upic384.asm`.
- Esperimento UPIC 1.3 a 360 pixel e lavoro nei margini: `experiments/mupic/research/fp-raster-work/player_360_dict13.asm`.
- Wrapper di assemblaggio: `tools/assemble.py`.
- Palette del renderer emulato: `UE2-C64U-WebRust/vendor/trx64-core/src/render.rs`.

Questi riferimenti locali documentano il lavoro preliminare; non sono dipendenze disponibili in un clone di C-OS. I riferimenti pubblici sopra permettono di studiare i backend senza il workspace originale.

Il renderer locale di riferimento riporta una licenza GPL-3.0-only. Prima di integrare sorgenti esterni, registrare provenienza, revisione e licenza, conservandone gli avvisi. I mockup generati sono riferimenti visivi; icone e font per la build devono avere sorgenti e provenienza definiti.

## 22 Istruzioni di consegna al dev agent

Implementare C-OS seguendo M0–M8 nella **root della repository C-OS**. Le specifiche sono raccolte in `specs/`: usare questo documento insieme a LANGUAGE.md, ULTIMATE-API.md e NUMERICS.md; la UI approvata è C, con celle 32×32 coincidenti con le icone. Comandi di build e path degli artefatti sono relativi alla root della repository.

La struttura può iniziare piccola: sorgenti nativi, strumenti host, app, test e output di build. Non generare impalcature o interfacce per estensioni non necessarie all'MVP.

Usare i progetti esistenti come riferimenti e mantenere sorgenti, build e launcher di C-OS nella propria repository. Gli script di sviluppo non devono sostituire launcher o modificare configurazioni di altri progetti nel workspace.

A ogni milestone consegnare:

1. Artefatto avviabile o test host riproducibile.
2. Comando esatto per costruire ed eseguire.
3. Mappa della memoria e dimensioni effettive.
4. Risultati dei test pertinenti e delle misure necessarie.
5. Divergenze motivate dai parametri iniziali e limiti ancora aperti.

La prima consegna tecnica deve verificare renderer 320×200, RAM residente e durata del DMA prima di impegnarsi in un'implementazione grafica estesa. Il tooling host consigliato è Rust, secondo §15.3 e LANGUAGE.md; può progredire anche mentre si attende la qualifica hardware.

Il risultato finale dell'MVP include bootstrap PRG, pack REU, manifest e map file, sorgenti, compilatore C-Script, SDK Ultimate, toolchain del bytecode, reference VM, applicazioni dimostrative, test e rapporto di qualificazione. La normale build non deve scaricare dipendenze casuali né dipendere da percorsi di artefatti temporanei.

Non dichiarare completato il requisito di multitasking se le app devono fare yield; non dichiarare memoria lineare se l'app deve selezionare un banco; non dichiarare UI reattiva usando soltanto una schermata statica.
