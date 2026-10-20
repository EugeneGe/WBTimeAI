// @wbtime/domain · Task 实体（纯域对象：零 ORM / 零 Web import）。
//
// 字段与冻结契约 `contracts/schema.v0018.pg.normalized.json` → `tables[task].columns`
// **13 列逐一对应**（实测，见施工记录 T1-05 §3）。TS 侧类型按
// `contracts/db/type-map.csv` 的 `ts_target` 列落地：
//   uuid-string → string；varchar-passthrough → string；int32-number → number；
//   timestamptz-iso8601 → string（ISO-8601 串）；jsonb-opaque（ts_target=unknown）
//   → 本域收窄为 `JsonValue | null`（比 `unknown` 更强的域内约束，已登记）。

import { DOMAIN_ERROR_CODES, DomainError, invariant } from "../errors.js";
import {
  DEFAULT_EXECUTION_MODE,
  TASK_EXECUTION_MODES,
  type TaskExecutionMode,
} from "./task-execution-mode.js";
import {
  TASK_STATUSES,
  assertTransition,
  canTransition,
  type TaskStatus,
} from "./task-status.js";

/** JSONB 列（`payload` / `result`）的域内值域。 */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** `task` 表 varchar 列的实测长度上限（取自 normalized.json 的 type 字段）。 */
export const TASK_COLUMN_LIMITS = Object.freeze({
  /** `type` VARCHAR(100) NOT NULL */
  type: 100,
  /** `status` VARCHAR(50) NOT NULL */
  status: 50,
  /** `execution_mode` VARCHAR(20) NOT NULL */
  execution_mode: 20,
  /** `idempotency_key` VARCHAR(255) NULL（唯一索引 uq_task_idempotency_key） */
  idempotency_key: 255,
});

/** Task 实体的域属性（camelCase，13 字段 ≡ 13 列）。 */
export interface TaskProps {
  readonly id: string;
  readonly tenantId: string;
  readonly organizationId: string | null;
  readonly workspaceId: string | null;
  readonly type: string;
  readonly status: TaskStatus;
  readonly priority: number;
  readonly executionMode: TaskExecutionMode;
  readonly payload: JsonValue | null;
  readonly result: JsonValue | null;
  readonly idempotencyKey: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

/** `task` 表的行形状（snake_case，与契约列名逐字一致）。 */
export interface TaskRecord {
  readonly id: string;
  readonly tenant_id: string;
  readonly organization_id: string | null;
  readonly workspace_id: string | null;
  readonly type: string;
  readonly status: string;
  readonly priority: number;
  readonly execution_mode: string;
  readonly payload: JsonValue | null;
  readonly result: JsonValue | null;
  readonly idempotency_key: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

/** 建实体入参；缺省项取 **域层默认值**（见各字段注释，DB 侧无默认值）。 */
export interface TaskCreateInput {
  readonly id: string;
  readonly tenantId: string;
  readonly organizationId?: string | null;
  readonly workspaceId?: string | null;
  readonly type: string;
  /** 默认 `CREATED`（旧线 models.py:40）。 */
  readonly status?: TaskStatus;
  /** 默认 `0`（旧线 models.py:41）。 */
  readonly priority?: number;
  /** 默认 `INLINE`（旧线 models.py:42）。 */
  readonly executionMode?: TaskExecutionMode;
  readonly payload?: JsonValue | null;
  readonly result?: JsonValue | null;
  readonly idempotencyKey?: string | null;
  /** ISO-8601 时间戳；缺省取 `new Date().toISOString()`。 */
  readonly now?: string;
}

const UUID_SHAPE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

function isUuid(value: string): boolean {
  return UUID_SHAPE.test(value);
}

function validate(props: TaskProps): void {
  invariant(isUuid(props.id), "task.id 必须是 UUID 字符串", { field: "id", value: props.id });
  invariant(isUuid(props.tenantId), "task.tenant_id 必须是 UUID 字符串", {
    field: "tenant_id",
    value: props.tenantId,
  });
  invariant(
    props.organizationId === null || isUuid(props.organizationId),
    "task.organization_id 必须是 UUID 字符串或 null",
    { field: "organization_id", value: props.organizationId },
  );
  invariant(
    props.workspaceId === null || isUuid(props.workspaceId),
    "task.workspace_id 必须是 UUID 字符串或 null",
    { field: "workspace_id", value: props.workspaceId },
  );

  invariant(props.type.length > 0, "task.type 不得为空（NOT NULL）", { field: "type" });
  invariant(
    props.type.length <= TASK_COLUMN_LIMITS.type,
    `task.type 超出 VARCHAR(${TASK_COLUMN_LIMITS.type}) 上限`,
    { field: "type", length: props.type.length, limit: TASK_COLUMN_LIMITS.type },
  );

  invariant(
    TASK_STATUSES.includes(props.status),
    "task.status 不是已登记的状态枚举值",
    { field: "status", value: props.status, allowed: [...TASK_STATUSES] },
  );
  invariant(
    props.status.length <= TASK_COLUMN_LIMITS.status,
    `task.status 超出 VARCHAR(${TASK_COLUMN_LIMITS.status}) 上限`,
    { field: "status", limit: TASK_COLUMN_LIMITS.status },
  );

  invariant(Number.isInteger(props.priority), "task.priority 必须是整数（INTEGER NOT NULL）", {
    field: "priority",
    value: props.priority,
  });

  invariant(
    TASK_EXECUTION_MODES.includes(props.executionMode),
    "task.execution_mode 不是已登记的执行模式枚举值",
    { field: "execution_mode", value: props.executionMode, allowed: [...TASK_EXECUTION_MODES] },
  );
  invariant(
    props.executionMode.length <= TASK_COLUMN_LIMITS.execution_mode,
    `task.execution_mode 超出 VARCHAR(${TASK_COLUMN_LIMITS.execution_mode}) 上限`,
    { field: "execution_mode", limit: TASK_COLUMN_LIMITS.execution_mode },
  );

  invariant(
    props.idempotencyKey === null || props.idempotencyKey.length <= TASK_COLUMN_LIMITS.idempotency_key,
    `task.idempotency_key 超出 VARCHAR(${TASK_COLUMN_LIMITS.idempotency_key}) 上限`,
    { field: "idempotency_key", limit: TASK_COLUMN_LIMITS.idempotency_key },
  );

  invariant(isIso8601(props.createdAt), "task.created_at 必须是 ISO-8601 字符串", {
    field: "created_at",
    value: props.createdAt,
  });
  invariant(isIso8601(props.updatedAt), "task.updated_at 必须是 ISO-8601 字符串", {
    field: "updated_at",
    value: props.updatedAt,
  });
}

function isIso8601(value: string): boolean {
  return Number.isFinite(Date.parse(value));
}

/**
 * Task 实体（不可变：状态迁移返回新实例）。
 *
 * 不变量：① 13 字段与契约列对齐；② 受列类型约束的取值合法；③ 状态迁移须合法。
 */
export class Task {
  private readonly props: TaskProps;

  private constructor(props: TaskProps) {
    validate(props);
    this.props = Object.freeze({ ...props });
  }

  /** 新建实体（走全部不变量校验）。 */
  static create(input: TaskCreateInput): Task {
    const now = input.now ?? new Date().toISOString();
    return new Task({
      id: input.id,
      tenantId: input.tenantId,
      organizationId: input.organizationId ?? null,
      workspaceId: input.workspaceId ?? null,
      type: input.type,
      status: input.status ?? "CREATED",
      priority: input.priority ?? 0,
      executionMode: input.executionMode ?? DEFAULT_EXECUTION_MODE,
      payload: input.payload ?? null,
      result: input.result ?? null,
      idempotencyKey: input.idempotencyKey ?? null,
      createdAt: now,
      updatedAt: now,
    });
  }

  /** 由持久层行还原（同样走不变量校验，避免脏行进入域）。 */
  static fromRecord(record: TaskRecord): Task {
    return new Task({
      id: record.id,
      tenantId: record.tenant_id,
      organizationId: record.organization_id,
      workspaceId: record.workspace_id,
      type: record.type,
      status: record.status as TaskStatus,
      priority: record.priority,
      executionMode: record.execution_mode as TaskExecutionMode,
      payload: record.payload,
      result: record.result,
      idempotencyKey: record.idempotency_key,
      createdAt: record.created_at,
      updatedAt: record.updated_at,
    });
  }

  /** 导出为 `task` 表行形状（列名与契约逐字一致）。 */
  toRecord(): TaskRecord {
    const p = this.props;
    return {
      id: p.id,
      tenant_id: p.tenantId,
      organization_id: p.organizationId,
      workspace_id: p.workspaceId,
      type: p.type,
      status: p.status,
      priority: p.priority,
      execution_mode: p.executionMode,
      payload: p.payload,
      result: p.result,
      idempotency_key: p.idempotencyKey,
      created_at: p.createdAt,
      updated_at: p.updatedAt,
    };
  }

  get id(): string {
    return this.props.id;
  }
  get tenantId(): string {
    return this.props.tenantId;
  }
  get organizationId(): string | null {
    return this.props.organizationId;
  }
  get workspaceId(): string | null {
    return this.props.workspaceId;
  }
  get type(): string {
    return this.props.type;
  }
  get status(): TaskStatus {
    return this.props.status;
  }
  get priority(): number {
    return this.props.priority;
  }
  get executionMode(): TaskExecutionMode {
    return this.props.executionMode;
  }
  get payload(): JsonValue | null {
    return this.props.payload;
  }
  get result(): JsonValue | null {
    return this.props.result;
  }
  get idempotencyKey(): string | null {
    return this.props.idempotencyKey;
  }
  get createdAt(): string {
    return this.props.createdAt;
  }
  get updatedAt(): string {
    return this.props.updatedAt;
  }

  /** 当前状态是否可迁移到 `next`。 */
  canTransitionTo(next: TaskStatus): boolean {
    return canTransition(this.props.status, next);
  }

  /**
   * 状态迁移（不可变：返回新实例并刷新 `updatedAt`）。
   *
   * @throws DomainError `VALIDATION_ERROR` —— 非法迁移。
   */
  transitionTo(next: TaskStatus, at: string = new Date().toISOString()): Task {
    assertTransition(this.props.status, next);
    return new Task({ ...this.props, status: next, updatedAt: at });
  }

  /**
   * 写入执行结果（仅 `RUNNING → SUCCESS|FAILED|CANCELLED` 路径的结果落库）。
   *
   * @throws DomainError `VALIDATION_ERROR` —— 非法迁移。
   */
  completeWith(next: TaskStatus, result: JsonValue | null, at?: string): Task {
    const moved = this.transitionTo(next, at);
    return new Task({ ...moved.props, result });
  }
}

/** 便于断言的运行时错误码出口（域层错误码以 contracts/errors.json 为准）。 */
export const TASK_ERROR_CODES = DOMAIN_ERROR_CODES;
export { DomainError as TaskDomainError };
