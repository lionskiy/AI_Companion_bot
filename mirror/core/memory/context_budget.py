class ContextBudget:
    def fit(
        self,
        facts: list[dict],
        episodes: list[dict],
        max_tokens: int,
        pinned_threshold: float = 0.85,
    ) -> tuple[list[dict], list[dict]]:
        """
        Trims facts and episodes to fit within max_tokens budget.
        Order of inclusion:
          1. Pinned facts (importance >= pinned_threshold) — always included
          2. Remaining facts sorted by final_score DESC
          3. Episodes sorted by final_score DESC
        Token count approximated as len(text) // 4.
        """
        pinned = [f for f in facts if f.get("importance", 0) >= pinned_threshold]
        rest_facts = [f for f in facts if f.get("importance", 0) < pinned_threshold]

        result_facts: list[dict] = list(pinned)
        result_episodes: list[dict] = []
        used = sum(len(str(f)) // 4 for f in result_facts)

        for f in sorted(rest_facts, key=lambda x: x.get("final_score", 0), reverse=True):
            cost = len(str(f)) // 4
            if used + cost > max_tokens:
                break
            result_facts.append(f)
            used += cost

        for ep in sorted(episodes, key=lambda x: x.get("final_score", 0), reverse=True):
            cost = len(ep.get("summary", "")) // 4
            if used + cost > max_tokens:
                break
            result_episodes.append(ep)
            used += cost

        return result_facts, result_episodes
