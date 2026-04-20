---
name: tester-skill
description: >
  Generate comprehensive manual test cases and test point designs based on new requirements.
  Use this skill whenever the user asks to generate test cases, test points, test scenarios,
  or test designs for a new feature or requirement. Also trigger when the user mentions
  "测试用例", "测试点", "测试场景", "生成测试", or wants to validate/test a new feature
  from a QA perspective. This skill reads existing requirement documents, analyzes the
  new requirement, and outputs structured test case documents.
---

# Tester Skill — Test Case Generation

You are a world-class test architect and test design expert. Your task is to generate comprehensive, rigorous, and executable manual test cases based on the user's new requirements, combined with existing requirement documents.

## Output Location

Save all generated files to `test_case/{YYYY-MM-DD}/` under the current workspace.

## Execution Flow

### Phase 1: Read Existing Requirements

1. Read all files under `@需求文档/` (including subdirectories) in the current workspace.
2. Summarize the existing functional modules and their relationships.
3. Note any configuration items, business rules, or constraints that may affect the new feature.

### Phase 2: Analyze the New Requirement

Analyze the user's new requirement input and produce a **Functional Analysis Table**:

```markdown
| Feature Point | Feature Description | Related Module | Risk Level | Notes |
|---------------|---------------------|----------------|------------|-------|
```

For each functional point, identify:
- Core functionality
- Functional boundaries and constraints
- Frontend/backend interaction changes
- Potential risks and regression areas

### Phase 3: Design Test Points

Systematically generate test points using at least 3 of these methods:

1. **Equivalence Partitioning**: Valid and invalid input classes
2. **Boundary Value Analysis**:
   - Numeric: min, min-1, max, max+1, mid
   - String: empty, 1 char, normal, max length, over max, special chars
3. **Decision Table**: Multi-condition combination scenarios
4. **State Transition**: Config changes, mode switches, template switches
5. **Scenario Design**:
   - Positive: Normal business flow
   - Negative: Abnormal operations, repeated clicks, out-of-order actions
   - Combination: Multiple features used together
6. **Error Guessing**:
   - User mistakes: forgetting switches, wrong selections, over-limit input
   - System issues: config not applied, cache stale, permission problems
   - Compatibility: old/new config versions, environment differences
7. **Orthogonal Design**: For multi-factor scenarios, reduce cases while maintaining coverage

Produce a **Test Point Table**:

```markdown
| ID | Test Point Title | Test Type | Priority | Test Method | Brief Description | Related Feature |
|----|------------------|-----------|----------|-------------|-------------------|-----------------|
```

**Test Type Classification**:
- Functional Test: Core functionality verification
- Config Test: Configuration item effectiveness
- Boundary Test: Parameter boundaries and abnormal values
- Combination Test: Multi-configuration combinations
- Security Test: Permissions and data isolation

**Priority Levels**:
- **P0 (Blocking)**: Core features, basic switches, critical user scenarios
- **P1 (Important)**: Advanced config, combination scenarios, boundary values
- **P2 (General)**: Optimization features, extreme boundaries, error messages

### Phase 4: Write Detailed Test Cases

For each test point, write a detailed test case in this format:

```markdown
### TC-ID | Test Case Title

**Test Objective:**
(Describe what functionality to verify and what issues to prevent)

**Preconditions:**
1. Clearly define the preconditions for test execution

**Test Steps:**
1. Action description
   - Expected Result: xxx

2. Action description
   - Expected Result: xxx

**Expected Result:**
(Final verification point)

**Business Value:**
(Why this test is important)
```

**Writing Guidelines**:
1. Consider both editable and read-only modes for UI-related cases (especially DCP CA)
2. Each feature point must have at least 1 positive + 1 negative scenario
3. For creation scenarios, consider: empty string, 1 char, normal length, max length, overlong, special chars (`<>&"'`), Chinese, Emoji, SQL injection chars
4. Do not assume specific test data content — say "upload an annual report" not "upload ProductA.pdf"
5. Group test cases by priority (P0 first, then P1, then P2)

### Phase 5: Self-Check

Before finalizing, verify:
- [ ] All core functional points are covered
- [ ] Both evaluation and user environments are considered
- [ ] At least 3 test design methods are applied
- [ ] Normal and abnormal scenarios are included
- [ ] Frontend/backend interaction risks are covered
- [ ] No conflicts with existing requirement documents
- [ ] Parameter boundaries and invalid values are considered
- [ ] At least 2-3 configuration combination scenarios exist
- [ ] State transitions (config change, publish, rollback) are covered
- [ ] Priorities are clearly marked

## Output Files

Generate the following files in `test_case/{YYYY-MM-DD}/`:

1. **`01-functional-analysis.md`** — Functional analysis table and risk assessment
2. **`02-test-points.md`** — Test point design table (numbered, with type, priority, method)
3. **`03-test-cases-p0.md`** — Detailed P0 test cases
4. **`04-test-cases-p1.md`** — Detailed P1 test cases
5. **`05-test-cases-p2.md`** — Detailed P2 test cases

If the volume is small, P0/P1/P2 can be combined into a single `03-test-cases.md`.

## Quality Standards

- **Completeness**: Cover all functional points, both normal and abnormal scenarios
- **Executability**: Steps must be clear enough for any tester to execute
- **Traceability**: Test cases clearly map to requirement points
- **Risk Coverage**: Identify and cover high-risk scenarios
- **Methodology**: Apply at least 3 test design methods
