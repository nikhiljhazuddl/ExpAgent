# Screenshots

Phase 12 end-to-end was verified via headless HTTP checks because no graphical
browser was attached to this build session. The verification artefacts:

- API responses captured in the run log of Phase 12 in the build transcript
- Rendered HTML snapshots in /tmp/dash_ae.html, /tmp/dash_csm.html,
  /tmp/dash_revops.html, /tmp/notif.html during that run
- Feedback round-trip → apps/agent/run_log/outcomes.csv (timestamp 2026-05-18T12:52:31)

To capture proper screenshots locally:
  1. make dev
  2. open http://localhost:3000/login
  3. login as: AE / Bhargav Prasad — screenshot dashboard + one signal detail page
                CSM / Janhvi Gupta — screenshot dashboard + notifications
                RevOps / RevOps Lead — screenshot dashboard funnel
  4. save PNGs in this directory
