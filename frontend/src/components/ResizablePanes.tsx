import React, { useState, useRef, useCallback } from 'react';

interface ResizablePanesProps {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultLeftWidth?: number;
  minLeftWidth?: number;
  maxLeftWidth?: number;
}

export const ResizablePanes: React.FC<ResizablePanesProps> = ({
  left,
  right,
  defaultLeftWidth = 50,
  minLeftWidth = 20,
  maxLeftWidth = 80,
}) => {
  const [leftWidth, setLeftWidth] = useState(defaultLeftWidth);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging || !containerRef.current) return;
      const container = containerRef.current;
      const containerRect = container.getBoundingClientRect();
      const newLeftWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100;
      const clampedWidth = Math.max(minLeftWidth, Math.min(maxLeftWidth, newLeftWidth));
      setLeftWidth(clampedWidth);
    },
    [isDragging, minLeftWidth, maxLeftWidth]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  React.useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  return (
    <div ref={containerRef} className="flex h-full bg-gray-100 dark:bg-gray-900">
      <div style={{ width: `${leftWidth}%` }} className="flex-shrink-0">
        {left}
      </div>

      {/* Divider handle */}
      <div
        className={`relative w-2 flex-shrink-0 cursor-col-resize group transition-all ${
          isDragging ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-gray-200 dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-blue-900/20'
        }`}
        onMouseDown={handleMouseDown}
      >
        {/* Dots indicator */}
        <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 flex flex-col items-center justify-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <div className={`w-1 h-1 rounded-full ${isDragging ? 'bg-blue-500' : 'bg-gray-400 dark:bg-gray-500'}`}></div>
          <div className={`w-1 h-1 rounded-full ${isDragging ? 'bg-blue-500' : 'bg-gray-400 dark:bg-gray-500'}`}></div>
          <div className={`w-1 h-1 rounded-full ${isDragging ? 'bg-blue-500' : 'bg-gray-400 dark:bg-gray-500'}`}></div>
        </div>
        {/* Active line */}
        <div className={`absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 transition-all ${
          isDragging ? 'bg-blue-500 shadow-lg shadow-blue-500/50' : 'bg-gray-300 dark:bg-gray-600 group-hover:bg-blue-400'
        }`}></div>
      </div>
      
      <div className="flex-1">
        {right}
      </div>
    </div>
  );
};