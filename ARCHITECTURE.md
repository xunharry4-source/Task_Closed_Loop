# Python 架构 V0.1

## Integration Layer

Ports:
- ResourceDiscoveryPort
- ResourceReadPort
- CapabilityDiscoveryPort
- ActionExecutionPort

Adapters 按需组合这些接口。

## Runtime Core

1. Reality Engine
2. Task Continuity Engine
3. Task Generation Engine
4. Execution Runtime
5. Persistence

## Offline Diagnostics

- R1 Context Scope Integrity
- R2 Evidence Identity & Availability Continuity
- R3 Execution Effect Continuity
- R4 Current Execution Context Revalidation
- R5 Information Flow & Disclosure Boundary

R1–R5 只做离线测试和定位。
