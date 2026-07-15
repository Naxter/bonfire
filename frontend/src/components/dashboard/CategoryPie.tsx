"use client"

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { categoryColor } from "@/lib/theme";
import { useChartTheme } from "@/lib/use-chart-theme";
import { useI18n } from "@/lib/i18n";
import type { CategorySpend } from "@/lib/api";

interface CustomTooltipProps {
  active?: boolean;
  // recharts merges the Cell's fill into the hovered slice's datum
  payload?: { payload: CategorySpend & { fill?: string } }[];
}

const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="rounded-lg border border-border bg-popover/95 p-2 shadow-[0_8px_24px_-10px_rgba(0,0,0,0.6)] backdrop-blur flex items-center gap-2">
        <div className="h-3 w-3 rounded-full" style={{ backgroundColor: data.fill }}></div>
        <span className="text-sm font-medium">{data.name}:</span>
        <span className="text-sm font-bold">€{data.value.toFixed(2)}</span>
      </div>
    )
  }
  return null
};

interface CategoryPieProps {
  data: CategorySpend[];
  activeCategory?: string | null;
  onSelect?: (name: string) => void;
}

export function CategoryPie({ data, activeCategory = null, onSelect }: CategoryPieProps) {
  const chart = useChartTheme();
  const { t } = useI18n();
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] w-full items-center justify-center text-sm text-muted-foreground">
        {t("analytics.noPeriodData")}
      </div>
    );
  }

  const clickable = !!onSelect;
  const isDimmed = (name: string) => !!activeCategory && activeCategory !== name;

  return (
    <div className="flex flex-col items-center w-full">
      <div className="w-full h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={75}
              outerRadius={110}
              paddingAngle={2}
              dataKey="value"
              nameKey="name"
              strokeWidth={2}
              stroke={chart.pieStroke}
              onClick={onSelect ? (slice) => slice.name && onSelect(String(slice.name)) : undefined}
            >
              {data.map((entry, index) => {
                const sliceColor = categoryColor(entry.name, index);
                const dimmed = isDimmed(entry.name);
                return (
                  <Cell
                    key={`cell-${index}`}
                    fill={sliceColor}
                    fillOpacity={dimmed ? 0.25 : 1}
                    style={{
                      outline: 'none',
                      cursor: clickable ? 'pointer' : 'default',
                      transition: 'fill-opacity 0.2s ease',
                    }}
                  />
                );
              })}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-wrap justify-center gap-x-4 gap-y-3 pt-6 w-full px-2">
        {data.map((entry, index) => {
          const sliceColor = categoryColor(entry.name, index);
          const active = activeCategory === entry.name;
          return (
            <button
              key={`legend-${index}`}
              type="button"
              onClick={onSelect ? () => onSelect(entry.name) : undefined}
              className={`flex items-center gap-1.5 rounded-md px-1.5 py-0.5 transition-colors ${
                clickable ? "cursor-pointer hover:bg-secondary/60" : "cursor-default"
              } ${active ? "bg-primary/10 ring-1 ring-primary/30" : ""} ${
                isDimmed(entry.name) ? "opacity-50" : ""
              }`}
            >
              <div
                className="h-3 w-3 rounded-full shrink-0"
                style={{ backgroundColor: sliceColor }}
              ></div>
              <span className="text-xs text-muted-foreground font-medium">{entry.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
