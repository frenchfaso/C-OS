//! Deterministic syscall boundary for host tests, not an Ultimate SDK backend.
use crate::vm::{FaultCause, Memory, ReturnValues, Syscall, Vm};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ServiceState {
    Complete,
    Pending,
    WaitMemory { line: u32 },
    Exited,
}

enum Work {
    Sleep {
        start: u32,
        frames: u16,
    },
    Fill {
        destination: u32,
        value: u8,
        length: u32,
        done: u32,
    },
    Copy {
        destination: u32,
        source: u32,
        length: u32,
        done: u32,
        backward: bool,
    },
}

struct Pending {
    owner: u64,
    call: Syscall,
    work: Work,
}

pub struct Harness {
    pub frame: u32,
    pub quantum: u8,
    pub calls: u64,
    pub chunks: u64,
    pending: Option<Pending>,
}

impl Default for Harness {
    fn default() -> Self {
        Self::new()
    }
}

impl Harness {
    pub fn new() -> Self {
        Self {
            frame: 0,
            quantum: 128,
            calls: 0,
            chunks: 0,
            pending: None,
        }
    }

    pub fn accept(
        &mut self,
        vm: &mut Vm,
        _memory: &mut Memory,
        call: &Syscall,
    ) -> Result<ServiceState, String> {
        if vm.pending_syscall() != Some(call) {
            return Err("request is not the VM's pending syscall".into());
        }
        if let Some(pending) = &self.pending {
            if pending.owner == vm.identity && pending.call == *call {
                return Ok(ServiceState::Pending);
            }
            return Err("harness already owns a pending request".into());
        }
        self.calls += 1;
        let mut result = ReturnValues::status(0);
        match call.id {
            0x00 => {
                vm.exit_syscall(call.token, call.r[0])?;
                return Ok(ServiceState::Exited);
            }
            0x01 => {
                result.r[1] = Some(crate::ABI);
                result.r[2] = Some(320);
                result.r[3] = Some(200);
                result.r[4] = Some(0);
            }
            0x02 => {
                result.r[1] = Some(self.frame as u16);
                result.r[2] = Some((self.frame >> 16) as u16);
            }
            0x03 => {
                if call.r[0] == 0 {
                    vm.refuel(0);
                } else {
                    self.pending = Some(Pending {
                        owner: vm.identity,
                        call: call.clone(),
                        work: Work::Sleep {
                            start: self.frame,
                            frames: call.r[0],
                        },
                    });
                    return Ok(ServiceState::Pending);
                }
            }
            0x0a | 0x0b => {
                let length = u32::from(call.r[2]) | (u32::from(call.r[3]) << 16);
                let validation = vm.check_access(call.p[0], length, true).and_then(|()| {
                    if call.id == 0x0b {
                        vm.check_access(call.p[1], length, false)
                    } else {
                        Ok(())
                    }
                });
                if call.id == 0x0a && call.r[1] > 255 {
                    result.status = 1;
                } else if let Err(cause) = validation {
                    result.status = if cause == FaultCause::ReadOnly { 9 } else { 2 };
                } else if length != 0 {
                    let work = if call.id == 0x0a {
                        Work::Fill {
                            destination: call.p[0],
                            value: call.r[1] as u8,
                            length,
                            done: 0,
                        }
                    } else {
                        Work::Copy {
                            destination: call.p[0],
                            source: call.p[1],
                            length,
                            done: 0,
                            backward: call.p[0] > call.p[1]
                                && u64::from(call.p[0]) < u64::from(call.p[1]) + u64::from(length),
                        }
                    };
                    self.pending = Some(Pending {
                        owner: vm.identity,
                        call: call.clone(),
                        work,
                    });
                    return Ok(ServiceState::Pending);
                }
            }
            0x0c => {
                result.p = [
                    Some(vm.bounds.heap.first),
                    Some(vm.bounds.heap.last),
                    Some(vm.bounds.stack.first),
                    Some(vm.bounds.stack.last),
                ];
            }
            id => {
                // Known deferred services report ENOTSUP; unknown/reserved IDs report ENOSYS.
                result.status = if is_known(id) { 11 } else { 6 };
                for &index in r_outputs(id) {
                    result.r[index] = Some(0);
                }
            }
        }
        vm.complete_syscall(call.token, result)?;
        Ok(ServiceState::Complete)
    }

    /// Complete at most 128 bytes of native CPU work. No new opcode credit is assigned.
    pub fn tick(&mut self, vm: &mut Vm, memory: &mut Memory) -> Result<ServiceState, String> {
        let pending = self.pending.as_mut().ok_or("no pending harness job")?;
        if pending.owner != vm.identity || vm.pending_syscall() != Some(&pending.call) {
            return Err("job owner has no matching continuation".into());
        }
        let work = &mut pending.work;
        let complete = match work {
            Work::Sleep { start, frames } => self.frame.wrapping_sub(*start) >= u32::from(*frames),
            Work::Fill {
                destination,
                value,
                length,
                done,
            } => {
                let size = (*length - *done).min(128);
                if let Some(line) = memory.missing(*destination + *done, size) {
                    return Ok(ServiceState::WaitMemory { line });
                }
                memory.write(*destination + *done, &vec![*value; size as usize])?;
                *done += size;
                self.chunks += 1;
                *done == *length
            }
            Work::Copy {
                destination,
                source,
                length,
                done,
                backward,
            } => {
                let size = (*length - *done).min(128);
                let offset = if *backward {
                    *length - *done - size
                } else {
                    *done
                };
                for address in [*source + offset, *destination + offset] {
                    if let Some(line) = memory.missing(address, size) {
                        return Ok(ServiceState::WaitMemory { line });
                    }
                }
                let bytes = memory.read(*source + offset, size)?.to_vec();
                memory.write(*destination + offset, &bytes)?;
                *done += size;
                self.chunks += 1;
                *done == *length
            }
        };
        if complete {
            let token = pending.call.token;
            let external_wait = matches!(work, Work::Sleep { .. });
            vm.complete_syscall(token, ReturnValues::status(0))?;
            if external_wait {
                vm.refuel(self.quantum);
            }
            self.pending = None;
            Ok(ServiceState::Complete)
        } else {
            Ok(ServiceState::Pending)
        }
    }
}

fn is_known(id: u8) -> bool {
    matches!(id, 0x00..=0x0d | 0x20..=0x2d | 0x30 | 0x40..=0x43 | 0x50..=0x56 | 0x60..=0x61 | 0x70..=0x73)
}

fn r_outputs(id: u8) -> &'static [usize] {
    match id {
        0x05 | 0x20 | 0x28 | 0x29 | 0x40 | 0x50 | 0x56 => &[1],
        0x22 | 0x23 | 0x25 | 0x26 | 0x61 => &[1, 2],
        0x0d => &[1, 2, 3, 4],
        0x30 => &[2, 3],
        0x72 => &[1, 2, 3],
        _ => &[],
    }
}
