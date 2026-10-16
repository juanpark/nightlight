"use client";

import { LogoIcon } from "../brand/Logo";
import { Icon } from "./Icon";
import s from "./Story.module.css";

// The product loop on the sample home, drawn as the app draws it.

function Light({ tone, word }: { tone: "ok" | "warn"; word: string }) {
  return (
    <span className={s.light} data-tone={tone}>
      <Icon name={tone === "ok" ? "check" : "alert"} size={14} />
      {word}
    </span>
  );
}

export function NoticeCard() {
  return (
    <div className={s.card}>
      <div className={s.needs}>
        <span className={s.needsDot} />
        <strong>1 thing needs you</strong>
        <span className={s.needsRest}>5 devices are fine</span>
      </div>
      <div className={s.node}>
        <div className={s.nodeHead}>
          <div>
            <p className={s.nodeName}>Raspberry Pi</p>
            <p className={s.nodeMeta}>Attic · Sample</p>
          </div>
          <Light tone="warn" word="Needs a look" />
        </div>
        <p className={s.nodePurpose}>Runs the home VPN and logs data from the car.</p>
        <p className={s.nodeProblem}>The disk is almost full.</p>
        <div className={s.meter} role="img" aria-label="Disk 94% full">
          <span style={{ width: "94%" }} />
        </div>
        <p className={s.meterLabel}>
          <span>Disk</span>
          <span>94% full</span>
        </p>
      </div>
    </div>
  );
}

export function ExplainCard() {
  return (
    <div className={s.card}>
      <p className={s.you}>Is anything wrong at home?</p>
      <ul className={s.steps}>
        <li><Icon name="check" size={15} />Checked 6 devices</li>
        <li><Icon name="check" size={15} />Looked at the Pi’s biggest folders</li>
        <li><Icon name="check" size={15} />Read its notes from last time</li>
      </ul>
      <div className={s.reply}>
        <LogoIcon size={28} className={s.avatar} />
        <p>
          Just one thing. Your Raspberry Pi’s disk is 94% full, mostly old log files from the car-data
          logger: 5.2 GB from before September. Clearing them is safe, and I can show you exactly what
          would go first.
        </p>
      </div>
    </div>
  );
}

export type ApprovalState = "waiting" | "running" | "done" | "declined";

export function ApprovalCard({ state, onChange }: { state: ApprovalState; onChange: (s: ApprovalState) => void }) {
  return (
    <div className={s.card} data-approval={state}>
      <div className={s.approvalHead}>
        <p className={s.approvalTitle}>Clean up old logs on the Raspberry Pi</p>
        <span className={s.risk}>
          <Icon name="shield" size={14} />
          Safe
        </span>
      </div>
      <dl className={s.facts}>
        <div>
          <dt><Icon name="plan" size={16} />What I’ll do</dt>
          <dd>Delete the car-data logger’s log files older than 30 days.</dd>
        </div>
        <div>
          <dt><Icon name="eye" size={16} />Dry run</dt>
          <dd>412 files, 5.2 GB. The disk goes from 94% to 61%.</dd>
        </div>
        <div>
          <dt><Icon name="touch" size={16} />What it touches</dt>
          <dd>Only that one log folder. The VPN and the logger keep running.</dd>
        </div>
        <div>
          <dt><Icon name="undo" size={16} />How to undo</dt>
          <dd>It can’t be undone: deleted logs are gone. Nothing else changes.</dd>
        </div>
      </dl>

      <div className={s.approvalFoot} aria-live="polite">
        {state === "waiting" && (
          <div className={s.approvalActions}>
            <button type="button" className={s.approve} onClick={() => onChange("running")}>
              Approve
            </button>
            <button type="button" className={s.notNow} onClick={() => onChange("declined")}>
              Not now
            </button>
          </div>
        )}
        {state === "running" && (
          <p className={s.status}>
            <span className={s.spinner} aria-hidden="true" />
            Cleaning up 412 files…
          </p>
        )}
        {state === "done" && (
          <p className={s.status} data-tone="ok">
            <Icon name="check" size={16} />
            Done. Freed 5.2 GB, and the disk is at 61%.
          </p>
        )}
        {state === "declined" && (
          <p className={s.status}>
            Okay, I won’t touch it. I’ll bring it up again if it gets worse.{" "}
            <button type="button" className={s.link} onClick={() => onChange("waiting")}>
              Show the card again
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

const LADDER = [
  { name: "Always ask me", does: "Explains and waits for your tap." },
  { name: "Ask me for new things", does: "Does familiar safe jobs on its own, asks about anything new." },
  { name: "Just handle it and tell me", does: "Acts, then reports in plain words." },
];

export type TrustState = "offer" | "yes" | "no";

export function TrustCard({ state, onChange }: { state: TrustState; onChange: (s: TrustState) => void }) {
  const level = state === "yes" ? 1 : 0;
  return (
    <div className={s.card}>
      <div className={s.reply}>
        <LogoIcon size={28} className={s.avatar} />
        <p>
          That’s the third time we’ve cleaned up old logs on the Pi, each time with your OK. Want me to do this
          one on my own from now on? I’ll still ask about anything new.
        </p>
      </div>
      <div className={s.approvalFoot} aria-live="polite">
        {state === "offer" ? (
          <div className={s.approvalActions}>
            <button type="button" className={s.approve} onClick={() => onChange("yes")}>
              Yes, handle it
            </button>
            <button type="button" className={s.notNow} onClick={() => onChange("no")}>
              Keep asking me
            </button>
          </div>
        ) : (
          <p className={s.status} data-tone={state === "yes" ? "ok" : undefined}>
            {state === "yes" ? <Icon name="check" size={16} /> : null}
            {state === "yes"
              ? "Clean-ups on the Pi moved up one step. You can move them back any time."
              : "Okay, I’ll keep asking every time."}{" "}
            <button type="button" className={s.link} onClick={() => onChange("offer")}>
              Undo
            </button>
          </p>
        )}
      </div>
      <ol className={s.ladder} aria-label="Trust for cleaning up old logs on the Pi">
        {LADDER.map((step, i) => (
          <li key={step.name} data-current={i === level || undefined}>
            <span className={s.rung} aria-hidden="true" />
            <span>
              <strong>{step.name}</strong>
              <span>{step.does}</span>
            </span>
            {i === level && <span className={s.now}>Now</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
