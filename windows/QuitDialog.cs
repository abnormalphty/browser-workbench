using System.Drawing;
using System.Windows.Forms;

namespace BrowserWorkbench
{
    /// <summary>Asked on quit while environments run: stop them, keep them running, or stay.</summary>
    sealed class QuitDialog : Form
    {
        public bool? StopEnvironments { get; private set; }

        public QuitDialog(int active)
        {
            Text = "Browser Workbench";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Font = new Font("Microsoft YaHei UI", 9F);
            Padding = new Padding(18);

            var layout = new TableLayoutPanel { AutoSize = true, ColumnCount = 1, Dock = DockStyle.Fill };
            layout.Controls.Add(new Label
            {
                Text = $"有 {active} 个浏览器环境还在运行",
                Font = new Font(Font.FontFamily, 11F, FontStyle.Bold),
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 8),
            });
            layout.Controls.Add(new Label
            {
                Text = "停止后会释放内存，登录状态会保留。也可以让它们在后台继续运行，下次打开时直接使用。",
                AutoSize = true,
                MaximumSize = new Size(LogicalToDeviceUnits(420), 0),
                Margin = new Padding(0, 0, 0, 16),
            });
            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, WrapContents = false };
            Button Add(string text, bool? choice)
            {
                var button = new Button { Text = text, AutoSize = true, Padding = new Padding(10, 4, 10, 4) };
                button.Click += (_, __) => { StopEnvironments = choice; DialogResult = choice == null ? DialogResult.Cancel : DialogResult.OK; };
                buttons.Controls.Add(button);
                return button;
            }
            var cancel = Add("取消", null);
            Add("保留运行并退出", false);
            var stop = Add("停止环境并退出", true);
            layout.Controls.Add(buttons);
            Controls.Add(layout);
            AcceptButton = stop;
            CancelButton = cancel;
        }
    }
}
