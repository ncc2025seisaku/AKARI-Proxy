---
description: Issue洗い出し→優先度分析→PR作成→マージの一連のサイクルを回すマスターワークフロー
---

# Issue消化サイクル（マスターワークフロー）

プロジェクトのタスクを体系的に消化するための統合ワークフローです。

## 概要フロー

```
┌─────────────────────────────────────────────────────────────┐
│  /issue-workflow                                            │
│  タスク洗い出し → Issue作成                                  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  /issue-priority-workflow                                   │
│  依存関係分析 → 優先度評価 → 次のIssue選出                    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  /pr-workflow                                               │
│  ブランチ作成 → 実装 → PR作成 → AI botレビュー確認 → マージ   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
                     ループ継続？
                      ├── Yes → /issue-priority-workflow へ
                      └── No → 終了
```

---

## フェーズ1: タスク洗い出し（初回のみ）

**使用ワークフロー**: `/issue-workflow`

```bash
# 現在のオープンIssue確認
gh issue list --state open

# Issueが少ない or なければ洗い出しを実行
```

**完了条件**: 着手可能なIssueが存在する

---

## フェーズ2: Issue選出

**使用ワークフロー**: `/issue-priority-workflow`

1. オープンIssue一覧を取得
2. 依存関係を分析
3. 優先度をスコアリング
4. 次に着手するIssueを決定

**選出基準（優先順）**:
1. CIが壊れていれば最優先
2. 依存なし＋短時間で完了
3. ブロッカーになっているもの

---

## フェーズ3: Issue対応

**使用ワークフロー**: `/pr-workflow`

1. ブランチ作成: `git checkout -b <prefix>/<issue-name>`
2. 実装・修正
3. コミット: `git commit -m "<prefix>: 説明 (#Issue番号)"`
4. プッシュ: `git push -u origin <branch>`
5. PR作成: `gh pr create --base develop ...`
6. AI botレビュー確認: `gh pr view <PR番号> --comments`
7. CI確認（ドキュメントのみなら待機不要）
8. マージ: `gh pr merge <PR番号> --squash --delete-branch`

---

## フェーズ4: ループ判断

マージ完了後、以下を確認:

```bash
# 残りのオープンIssue
gh issue list --state open --json number,title

# 作業時間の余裕
```

**継続する場合**: フェーズ2に戻る
**終了する場合**: 進捗をまとめて完了

---

## クイックリファレンス

| フェーズ | ワークフロー | 主なコマンド |
|---------|-------------|-------------|
| 洗い出し | `/issue-workflow` | `gh issue create` |
| 選出 | `/issue-priority-workflow` | `gh issue list` |
| 対応 | `/pr-workflow` | `gh pr create`, `gh pr merge` |

---

## セッション開始/終了コマンド

### セッション開始
```bash
# 現在の状態を確認
gh issue list --state open
gh run list --limit 3
```

### セッション終了
```bash
# 進捗確認
gh issue list --state closed --limit 5
```

---

## Tips

- **1セッション1-3 Issue** が理想的なペース
- **ドキュメント系は連続処理** - CIの影響が少ない
- **CI壊れたら即対応** - 他の作業をブロックする
- **大きいIssueは分割** - PRが小さいほどレビューが楽
