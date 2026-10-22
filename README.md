# 東京リシャフトラボ｜OPENストーリーズ自動投稿

火〜日の毎日11:00（日本時間）に、`photos` の写真に小さめの太字「OPEN」を載せてストーリーズへ自動投稿します。
写真とレイアウト（左上・左下・中央・右下・下中央＋線）は日替わりで、前回と同じにはなりません。月曜定休はお休みです。

## 普段の使い方
- **写真を増やす**：`photos` フォルダに写真を追加するだけ（JPEG/PNG、縦長がベスト）
- **臨時休業**：`config.json` の `skip_dates` に日付を追加。例 `["2026-12-31", "2027-01-01"]`
- **特定の写真で使わない位置**：`config.json` の `layout_rules` に指定（1=左上 2=左下 3=中央 4=右下 5=下中央）
- **文字の大きさ・字間**：`config.json` の `font_size` / `letter_spacing`

## 初回設定（GitHub）
1. GitHubで **Public** のリポジトリを作成し、このフォルダの中身をすべてアップロード
   （画像を Instagram に取り込ませるため公開URLが必要です。トークンは Secrets に暗号化保存されるので公開されません）
2. Settings → Secrets and variables → Actions → New repository secret
   - `IG_ACCESS_TOKEN`：Instagram の長期アクセストークン
   - `GH_PAT`：トークン自動更新用の GitHub トークン（Fine-grained、このリポジトリの **Secrets: Read and write** 権限のみ）
3. Settings → Actions → General → Workflow permissions を **Read and write permissions** に
4. Actions タブ →「毎日のOPENストーリーズ」→ Run workflow でテスト投稿（定休日でも今すぐ投稿されます）

## 仕組み
- `daily-open-story.yml`：10:45に起動 → 画像作成 → リポジトリに保存 → 11:00まで待って投稿
- `refresh-token.yml`：毎月1日・15日にトークンを更新（60日で切れるのを防止）
- 投稿は Instagram 公式 API（Instagram ログイン方式・ストーリーズ）を使用
- 生成画像は `out` に14日分だけ残し、古いものは自動削除
