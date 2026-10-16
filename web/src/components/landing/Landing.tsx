import { Logo } from "../brand/Logo";
import { MascotPose } from "../mascot/MascotPose";
import { AuthButtons } from "./AuthButtons";
import { Icon } from "./Icon";
import { NavBar } from "./NavBar";
import { Story } from "./Story";
import { display, sans } from "./fonts";
import s from "./Landing.module.css";

const DEVICES = [
  {
    name: "Raspberry Pi",
    room: "Attic",
    does: "Runs the home VPN and logs data from the car.",
    watches: "Disk space, the VPN, the logger’s job",
    tone: "warn" as const,
    state: "Disk almost full",
  },
  {
    name: "Mac Mini",
    room: "Living room",
    does: "Runs the home automation.",
    watches: "Memory, updates, background items that keep failing",
    tone: "ok" as const,
    state: "All good",
  },
  {
    name: "NAS",
    room: "Study",
    does: "Keeps the family photos.",
    watches: "Free space, the last backup",
    tone: "ok" as const,
    state: "All good",
  },
  {
    name: "Minecraft server",
    room: "Kids’ room",
    does: "Hosts the kids’ Minecraft world.",
    watches: "Lag, memory, world backups, updates",
    tone: "ok" as const,
    state: "All good",
  },
  {
    name: "Camera recorder",
    room: "Garage",
    does: "Records the driveway camera.",
    watches: "Whether it’s recording, free space",
    tone: "ok" as const,
    state: "All good",
  },
  {
    name: "Router",
    room: "Hallway",
    does: "Connects everything to the internet.",
    watches: "Whether the internet is up, name lookups",
    tone: "ok" as const,
    state: "All good",
  },
];

const SENDS = [
  "CPU, memory and disk use, and how long it’s been on",
  "Which programs and containers are running, and which have stopped",
  "How many software updates are waiting",
  "Two safety checks: passwordless admin rights, and SSH password logins",
  "The jobs you have allowed on that device",
];

const NEVER = [
  "Names of your machines, or IP and hardware addresses",
  "Your files",
  "Passwords, keys or environment variables",
  "Logs, unless you allow them for one thing, scrubbed on the device first",
];

const PEOPLE = [
  "A family with a NAS full of photos.",
  "A Raspberry Pi running the home VPN.",
  "A Minecraft world for the kids.",
  "Home automation on an old Mac Mini.",
  "A dental clinic with one small server.",
];

export function Landing() {
  return (
    <div className={`${s.page} ${display.variable} ${sans.variable}`} data-theme="night" data-landing id="top">
      <a href="#main" className={s.skip}>
        Skip to content
      </a>
      <NavBar />

      <main id="main">
        <Story
          hero={
            <>
              <h1 className={s.h1}>
                <span className={s.heavy}>A house‑sitter</span>{" "}
                <span className={s.thin}>for the machines you run at home.</span>
              </h1>
              <p className={s.lede}>
                Nightlight puts every device on one friendly map, explains problems in plain words, and fixes
                things only when you say yes.
              </p>
              <AuthButtons />
              <p className={s.fine}>The demo needs no account. It runs on a simulated sample home.</p>
              <a href="#how" className={s.scrollHint}>
                <span className={s.scrollLine} aria-hidden="true" />
                Follow tonight’s round
              </a>
            </>
          }
        />

        <section id="home" className={s.section} aria-labelledby="home-title">
          <div className={s.sectionHead}>
            <h2 id="home-title" className={s.h2}>
              One map for every machine you run.
            </h2>
            <p className={s.sectionLede}>
              Each device gets a health light and one plain sentence. This is the sample home the demo opens
              with: six machines, one of them asking for a look.
            </p>
          </div>

          <div className={s.ledger} role="table" aria-label="The sample home">
            <div className={s.ledgerHead} role="row">
              <span role="columnheader">Device</span>
              <span role="columnheader">Room</span>
              <span role="columnheader">What it does</span>
              <span role="columnheader">What Nightlight keeps an eye on</span>
              <span role="columnheader">Tonight</span>
            </div>
            {DEVICES.map((d) => (
              <div key={d.name} className={s.ledgerRow} role="row">
                <span role="cell" className={s.devName}>
                  {d.name}
                </span>
                <span role="cell" className={s.cellMuted}>
                  {d.room}
                </span>
                <span role="cell">{d.does}</span>
                <span role="cell" className={s.cellMuted}>
                  {d.watches}
                </span>
                <span role="cell" className={s.state} data-tone={d.tone}>
                  <Icon name={d.tone === "ok" ? "check" : "alert"} size={15} />
                  {d.state}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section id="privacy" className={`${s.section} ${s.privacy}`} aria-labelledby="privacy-title">
          <div className={s.sectionHead}>
            <h2 id="privacy-title" className={s.h2}>
              It changes nothing by default.
            </h2>
            <p className={s.sectionLede}>
              A small helper on each of your devices reports health facts once a minute. Before it does anything
              more, the device has to allow that job and you have to tap Approve.
            </p>
          </div>

          <div className={s.columns}>
            <div>
              <h3 className={s.h3}>What the helper sends</h3>
              <ul className={s.ruled}>
                {SENDS.map((t) => (
                  <li key={t}>
                    <Icon name="check" size={16} className={s.okIcon} />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className={s.h3}>What it never sends</h3>
              <ul className={s.ruled}>
                {NEVER.map((t) => (
                  <li key={t}>
                    <Icon name="x" size={16} className={s.noIcon} />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <dl className={s.promises}>
            <div>
              <dt>Every job on a real device waits for your tap.</dt>
              <dd>Whatever the trust settings say. Trust only grows on the sample home.</dd>
            </div>
            <div>
              <dt>Strict mode keeps the keys on the device.</dt>
              <dd>Permissions then change only on the machine itself; the app can’t widen them.</dd>
            </div>
            <div>
              <dt>Leaving is one line.</dt>
              <dd>The uninstall line stops the helper, deletes its files and revokes its key.</dd>
            </div>
          </dl>
        </section>

        <section className={`${s.section} ${s.people}`} aria-labelledby="people-title">
          <h2 id="people-title" className={s.h2}>
            For homes and small offices with no IT person.
          </h2>
          <ul className={s.peopleList}>
            {PEOPLE.map((p) => (
              <li key={p}>
                <span className={s.peopleDot} aria-hidden="true" />
                {p}
              </li>
            ))}
          </ul>
        </section>

        <section className={s.close} aria-labelledby="close-title">
          <div className={s.closeMascot}>
            <MascotPose pose="sit" size={200} />
          </div>
          <h2 id="close-title" className={s.closeTitle}>
            <span className={s.heavy}>Leave the light on.</span>
          </h2>
          <p className={s.closeLede}>
            Try Nightlight on the sample home in one click, or sign in with Google to add your own devices.
          </p>
          <AuthButtons />
        </section>
      </main>

      <footer className={s.footer}>
        <Logo height={20} />
        <p>A Gemini agent on Google Cloud, built for the Google Cloud AI Builder Cup 2026.</p>
        <p>Devices in the demo are simulated.</p>
      </footer>
    </div>
  );
}
