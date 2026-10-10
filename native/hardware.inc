#import "build_profile.inc"
// Original C-OS diagnostic interface; no external source is incorporated.
.const REPORT = $0300
.const SAVED = M3_BUILD != 0 ? $0600 : $1000
.const BUFFER = M3_BUILD != 0 ? $0700 : $1100
.const NYBBLES = $0200
.const REU = $df00
.const FIRST_LINE = 60
.const HEIGHT = 200
.const RASTER_IRQ = 58
.const LINE_DELAY = cmdLineVars.get("lineDelay").asNumber()
.const BUILD_TAG = cmdLineVars.get("buildTag").asNumber()
.const RENDER_BYTES = cmdLineVars.get("renderBytes").asNumber()
.const M2_BUILD = cmdLineVars.get("m2").asNumber()
.const MARGIN_ENABLED = cmdLineVars.get("marginEnabled").asNumber()
.const MARGIN_ENTRY = cmdLineVars.containsKey("marginEntry") ? cmdLineVars.get("marginEntry").asNumber() : $17e0
.const PACK_APP_COUNT = cmdLineVars.get("appCount").asNumber()
.label dma_local = $80
.label dma_reu = $82
.label dma_length = $85
.label dma_command = $87
.label scratch_ptr = $88
.label bank = $8a
.label before_timer = $8b
.label speed_high = $8d
.label timer_index = $8e
.label repetitions = $8f
.label saved_d031 = $90
.label row = $c0
.label nmi_pending = $c1
