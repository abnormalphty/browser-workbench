using System.Net;

namespace BrowserWorkbench
{
    /// <summary>Native page shown before the backend is reachable or after it fails.</summary>
    static class StatusPage
    {
        public static string Html(string message, string detail, bool isError)
        {
            var actions = isError
                ? "<div class=actions><a class=primary href='workbench-native://retry'>重试</a><a href='workbench-native://logs'>查看日志</a></div>"
                : "<div class=spinner></div>";
            return "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><style>" +
                ":root{color-scheme:light dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f6f5;color:#18241f;" +
                "font:15px \"Segoe UI\",\"Microsoft YaHei UI\",sans-serif}.card{text-align:center;max-width:460px;padding:40px}" +
                ".mark{width:64px;height:64px;margin:0 auto 22px;border-radius:16px;background:#21644e;color:#fff;display:grid;place-items:center;" +
                "font:600 32px \"Microsoft YaHei UI\",sans-serif}h1{font-size:20px;font-weight:600;margin:0 0 10px}p{color:#5d6964;line-height:1.7;margin:0}" +
                ".spinner{width:22px;height:22px;margin:26px auto 0;border:3px solid #e3e8e1;border-top-color:#21644e;border-radius:50%;" +
                "animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.actions{margin-top:26px;display:flex;gap:10px;justify-content:center}" +
                "a{padding:9px 18px;border-radius:9px;border:1px solid #e3e8e1;color:#203a33;text-decoration:none;background:#fff}" +
                "a.primary{background:#21644e;border-color:#21644e;color:#fff}" +
                "@media(prefers-color-scheme:dark){body{background:#191c1b;color:#e8edea}p{color:#8d9792}.spinner{border-color:#2c3230;border-top-color:#6fcca4}" +
                "a{background:#232827;border-color:rgba(255,255,255,.12);color:#e8edea}a.primary{background:#2a8262;border-color:#2a8262}}</style>" +
                $"<div class=card><div class=mark>境</div><h1>{WebUtility.HtmlEncode(message)}</h1><p>{WebUtility.HtmlEncode(detail)}</p>{actions}</div></html>";
        }
    }
}
