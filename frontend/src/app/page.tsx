import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <div className="container mx-auto p-8">
        <header className="mb-12">
          <h1 className="text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-violet-600 dark:from-blue-400 dark:to-violet-400">
            ZenithAlgo
          </h1>
          <p className="text-xl text-slate-600 dark:text-slate-400 mt-2">
            量化交易策略监控平台
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
          <Card className="p-6 hover:shadow-lg transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">系统状态</h3>
              <Badge variant="default" className="bg-green-500">运行中</Badge>
            </div>
            <p className="text-3xl font-bold text-slate-900 dark:text-slate-100">100%</p>
            <p className="text-sm text-slate-500 dark:text-slate-400">健康度</p>
          </Card>

          <Card className="p-6 hover:shadow-lg transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">总收益</h3>
              <Badge variant="secondary">YTD</Badge>
            </div>
            <p className="text-3xl font-bold text-green-600 dark:text-green-400">
              +12.5%
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">年初至今</p>
          </Card>

          <Card className="p-6 hover:shadow-lg transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">活跃策略</h3>
              <Badge variant="outline">2 / 5</Badge>
            </div>
            <p className="text-3xl font-bold text-slate-900 dark:text-slate-100">2</p>
            <p className="text-sm text-slate-500 dark:text-slate-400">正在运行</p>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="p-6">
            <h3 className="text-xl font-semibold mb-4">快速操作</h3>
            <div className="space-y-3">
              <Button className="w-full" variant="default" asChild>
                <a href="/backtest">查看回测结果</a>
              </Button>
              <Button className="w-full" variant="outline">
                运行新回测
              </Button>
              <Button className="w-full" variant="secondary">
                编辑配置
              </Button>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-xl font-semibold mb-4">最近交易</h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center p-3 bg-slate-50 dark:bg-slate-800 rounded">
                <div>
                  <p className="font-medium">BTCUSDT</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">买入</p>
                </div>
                <Badge className="bg-green-500">+2.1%</Badge>
              </div>
              <div className="flex justify-between items-center p-3 bg-slate-50 dark:bg-slate-800 rounded">
                <div>
                  <p className="font-medium">ETHUSDT</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">卖出</p>
                </div>
                <Badge className="bg-red-500">-0.8%</Badge>
              </div>
            </div>
          </Card>
        </div>

        <footer className="mt-12 text-center text-sm text-slate-500 dark:text-slate-400">
          <p>ZenithAlgo v0.1.0 | 后端健康检查: ✓</p>
        </footer>
      </div>
    </div>
  );
}
