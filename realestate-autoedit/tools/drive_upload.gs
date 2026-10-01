/**
 * 完成品をGoogleドライブに保存するための受け口(Google Apps Script)。
 * 自分のGoogleアカウントで1回だけ設定する(手順は README の「ドライブに自動保存」)。
 *
 * - マイドライブ/完成動画/<物件フォルダ名>/ にファイルを保存する(同じ名前のファイルは置き換え)
 * - KEY を知っている人だけが保存できる。KEY は自分で決めた長い文字列に変える
 */
const KEY = 'ここを自分で決めた長い文字列に変える';
const ROOT_FOLDER = '完成動画';

function doPost(e) {
  try {
    const p = JSON.parse(e.postData.contents);
    if (p.key !== KEY) return json_({ ok: false, error: 'key' });
    const root = child_(DriveApp.getRootFolder(), ROOT_FOLDER);
    const folder = child_(root, p.folder);
    const old = folder.getFilesByName(p.name);
    while (old.hasNext()) old.next().setTrashed(true);
    const blob = Utilities.newBlob(Utilities.base64Decode(p.data), p.mime, p.name);
    const file = folder.createFile(blob);
    return json_({ ok: true, id: file.getId(), url: file.getUrl(), folder: folder.getUrl() });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function child_(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
