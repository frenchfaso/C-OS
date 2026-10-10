#importonce
.const COS_APPLICATION_ABI = 2
// Missing flags retain the established M0/M2 diagnostic build contract.
.const EXTENDED_DIAGNOSTICS = cmdLineVars.containsKey("extendedDiagnostics") ? cmdLineVars.get("extendedDiagnostics").asNumber() : 1
.const M3_BUILD = cmdLineVars.containsKey("m3") ? cmdLineVars.get("m3").asNumber() : 0
