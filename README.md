# 大山 中古マンション3LDK ウォッチャー セットアップ手順

毎朝7時に SUUMO / HOME'S / at home をチェックし、新着・値下げがあればLINEに届きます。
---

## STEP 1 GitHubアカウントを作る（5分）

1. https://github.com を開き「Sign up」
2. メールアドレス・パスワード・ユーザー名を入力（ユーザー名は英数字、例: `conocira`）
3. 届いた確認メールのコードを入力して完了。プランは無料（Free）のまま

## STEP 2 リポジトリ（保存場所）を作る（3分）

1. 右上「＋」→「New repository」
2. Repository name: `oyama-watch`
3. **Private** を選択（自分だけ見える）
4. 「Create repository」

## STEP 3 ファイルをアップロードする（5分）

1. 作ったリポジトリのページで「uploading an existing file」のリンクをクリック
2. このフォルダの以下4ファイルをドラッグ＆ドロップ
   - `watcher.py`
   - `config.json`
   - `requirements.txt`
   - `README.md`
3. 「Commit changes」
4. **もう1つ別途作業**: `.github/workflows/watch.yml` はフォルダごと必要なので
   - リポジトリのページで「Add file」→「Create new file」
   - ファイル名欄に `.github/workflows/watch.yml` と入力（スラッシュを打つと自動でフォルダになります）
   - このフォルダの `watch.yml` の中身を全部コピーして貼り付け
   - 「Commit changes」

## STEP 4 検索URLを設定する（5分）

各サイトで「大山駅・中古マンション・3LDK・新着順」で検索し、その結果ページのURLをコピーします。

- SUUMO: https://suumo.jp → 中古マンション → 東京都 → 駅から探す → 東武東上線「大山」→ 間取り「3LDK」にチェック → 検索 → 並び替え「新着順」
- HOME'S: https://www.homes.co.jp → 中古マンション → 同様に大山駅・3LDK
- at home: https://www.athome.co.jp → 同様

GitHubで `config.json` を開き、鉛筆アイコン（Edit）→ `"ここに〜URLを貼る"` の部分を実際のURLに置き換え → 「Commit changes」。

> 貼るときは `"` で囲んだ中にURLを入れてください。URLに `&` が含まれていても問題ありません。

## STEP 5 LINE通知の準備（10分）

LINE Notifyは終了したので、無料の「LINE公式アカウント」を1つ作って自分に送る形にします。

1. https://developers.line.biz/console/ を開き、普段のLINEアカウントでログイン
2. 「プロバイダー作成」→ 名前は何でもOK（例: `myhome`）
3. 「Messaging API」チャネルを作成
   - チャネル名: `大山ウォッチ` など
   - 業種などは適当でOK
4. 作成したチャネルの **「チャネル基本設定」タブ** を開き、下の方にある **「あなたのユーザーID」**（`U` から始まる長い文字列）をコピー → メモ
5. **「Messaging API設定」タブ** を開き
   - 表示されているQRコードを自分のLINEで読み取り、友だち追加
   - 一番下の「チャネルアクセストークン（長期）」で「発行」→ 表示された長い文字列をコピー → メモ

> 無料プランは月200通まで送れます。1日1通なので十分です。

## STEP 6 GitHubにLINEの情報を登録する（3分）

1. リポジトリのページ → 「Settings」→ 左メニュー「Secrets and variables」→「Actions」
2. 「New repository secret」を2回
   - Name: `LINE_CHANNEL_ACCESS_TOKEN` / Secret: STEP5でメモしたトークン
   - Name: `LINE_USER_ID` / Secret: STEP5でメモしたユーザーID

## STEP 7 動作テスト（2分）

1. リポジトリのページ → 「Actions」タブ
2. 初回は「I understand my workflows, go ahead and enable them」を押す
3. 左の「大山3LDKウォッチ」→ 右の「Run workflow」→ 緑のボタン
4. 1〜2分後、LINEに「✅ 初回セットアップ完了。現在 XX件を記録しました」と届けば成功

届かない場合は Actions の実行ログを開いて、赤くなっている箇所のテキストをそのままClaudeに貼ってください。

---

## 以降の動き

- 毎朝7時に自動実行。新着・値下げがあった日だけLINEが届きます
- 変化がない日も「変化なし」と送りたい場合は `config.json` の `notify_when_no_change` を `true` に
- 前日の状態は `state.json` として自動保存されます（自分で触る必要なし）

## 注意点

- HOME'S と at home は汎用的な読み取り方をしているため、初回に「0件（HTML構造変更の可能性）」と出る場合があります。その時はActionsのログを貼ってもらえれば調整します。SUUMO は専用パーサーなので安定しています
- 各サイトの利用規約上、自動アクセスはグレーです。アクセスは1日1回・ページ間3秒待機に抑えていますが、その点はご了承ください
- GitHubの無料枠（月2,000分）に対し、この仕組みは月30分程度しか使いません
