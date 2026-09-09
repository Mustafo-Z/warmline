<!--
The agent's pinned opening utterance. SPEC 4.4.

Fixed here rather than composed by the model, so that the disclosure does not
depend on the model choosing to make it. Everything below the comment is the
literal text spoken in turn one.

Three sentences, deliberately:

  1. Discloses the AI and names the principal.
  2. Makes the call's one commitment, as its own sentence so that the claim
     checker sees it and checks it against the allowlist. Joined to the
     question with a dash, it would ride along inside a question and escape
     review.
  3. Hands control to the prospect before anything is pitched.

This text is asserted against policy/disclosure.yaml and the prohibited
patterns in policy/permitted_claims.yaml by the test suite. It cannot drift out
of compliance with its own rules without the build going red.
-->

Hi, I'm an AI assistant calling on behalf of Meridian Communications. I'll keep this under a minute. Is now an okay time?
