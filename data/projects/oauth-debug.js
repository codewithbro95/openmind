const issue = {
  title: "OAuth redirect issue",
  app: "FleetPulse",
  symptoms: [
    "Login succeeds at provider",
    "Callback reaches local app",
    "Session cookie is not persisted after redirect"
  ],
  likelyFix: "Check SameSite cookie policy and callback URL environment variables"
};

console.log(issue);
