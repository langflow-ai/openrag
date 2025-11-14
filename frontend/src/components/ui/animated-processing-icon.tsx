const AnimatedProcessingIcon = ({
  className,
  props,
}: {
  className?: string;
  props?: React.SVGProps<SVGSVGElement>;
}) => {
  // CSS for the stepped animation states
  const animationCSS = `
    .state-1 { opacity: 1; animation: showState1 1.5s infinite steps(1, end); }
    .state-2 { opacity: 0; animation: showState2 1.5s infinite steps(1, end); }
    .state-3 { opacity: 0; animation: showState3 1.5s infinite steps(1, end); }
    .state-4 { opacity: 0; animation: showState4 1.5s infinite steps(1, end); }
    .state-5 { opacity: 0; animation: showState5 1.5s infinite steps(1, end); }
    .state-6 { opacity: 0; animation: showState6 1.5s infinite steps(1, end); }

    @keyframes showState1 {
      0%, 16.66% { opacity: 1; }
      16.67%, 100% { opacity: 0; }
    }

    @keyframes showState2 {
      0%, 16.66% { opacity: 0; }
      16.67%, 33.33% { opacity: 1; }
      33.34%, 100% { opacity: 0; }
    }

    @keyframes showState3 {
      0%, 33.33% { opacity: 0; }
      33.34%, 50% { opacity: 1; }
      50.01%, 100% { opacity: 0; }
    }

    @keyframes showState4 {
      0%, 50% { opacity: 0; }
      50.01%, 66.66% { opacity: 1; }
      66.67%, 100% { opacity: 0; }
    }

    @keyframes showState5 {
      0%, 66.66% { opacity: 0; }
      66.67%, 83.33% { opacity: 1; }
      83.34%, 100% { opacity: 0; }
    }

    @keyframes showState6 {
      0%, 83.33% { opacity: 0; }
      83.34%, 100% { opacity: 1; }
    }
  `;

  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...props}
    >
      {/* Inject animation styles into the SVG's shadow */}
      <style dangerouslySetInnerHTML={{ __html: animationCSS }} />

      {/* State 1 */}
      <g className="state-1">
        <rect
          x="-19.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
      </g>

      {/* State 2 */}
      <g className="state-2">
        <rect
          x="-53.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
        <path
          d="M7.625 20.375H8V20.75H8.375V22.25H8V23H5V22.25H4.625V20.75H5V20.375H5.375V19.625H7.625V20.375Z"
          fill="currentColor"
        />
        <path d="M4.625 20H3.125V18.5H4.625V20Z" fill="currentColor" />
        <path d="M9.875 20H8.375V18.5H9.875V20Z" fill="currentColor" />
        <path d="M6.125 18.5H4.625V17H6.125V18.5Z" fill="currentColor" />
        <path d="M8.375 18.5H6.875V17H8.375V18.5Z" fill="currentColor" />
      </g>

      {/* State 3 */}
      <g className="state-3">
        <rect
          x="-87.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
        <path
          d="M7.625 20.375H8V20.75H8.375V22.25H8V23H5V22.25H4.625V20.75H5V20.375H5.375V19.625H7.625V20.375Z"
          fill="currentColor"
        />
        <path d="M4.625 20H3.125V18.5H4.625V20Z" fill="currentColor" />
        <path d="M9.875 20H8.375V18.5H9.875V20Z" fill="currentColor" />
        <path d="M6.125 18.5H4.625V17H6.125V18.5Z" fill="currentColor" />
        <path d="M8.375 18.5H6.875V17H8.375V18.5Z" fill="currentColor" />
        <path
          d="M18.625 12.375H19V12.75H19.375V14.25H19V15H16V14.25H15.625V12.75H16V12.375H16.375V11.625H18.625V12.375Z"
          fill="currentColor"
        />
        <path d="M15.625 12H14.125V10.5H15.625V12Z" fill="currentColor" />
        <path d="M20.875 12H19.375V10.5H20.875V12Z" fill="currentColor" />
        <path d="M17.125 10.5H15.625V9H17.125V10.5Z" fill="currentColor" />
        <path d="M19.375 10.5H17.875V9H19.375V10.5Z" fill="currentColor" />
      </g>

      {/* State 4 */}
      <g className="state-4">
        <rect
          x="-122.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
        <path
          d="M7.625 4.375H8V4.75H8.375V6.25H8V7H5V6.25H4.625V4.75H5V4.375H5.375V3.625H7.625V4.375Z"
          fill="currentColor"
        />
        <path d="M4.625 4H3.125V2.5H4.625V4Z" fill="currentColor" />
        <path d="M9.875 4H8.375V2.5H9.875V4Z" fill="currentColor" />
        <path d="M6.125 2.5H4.625V1H6.125V2.5Z" fill="currentColor" />
        <path d="M8.375 2.5H6.875V1H8.375V2.5Z" fill="currentColor" />
        <g opacity="0.25">
          <path
            d="M7.625 20.375H8V20.75H8.375V22.25H8V23H5V22.25H4.625V20.75H5V20.375H5.375V19.625H7.625V20.375Z"
            fill="currentColor"
          />
          <path d="M4.625 20H3.125V18.5H4.625V20Z" fill="currentColor" />
          <path d="M9.875 20H8.375V18.5H9.875V20Z" fill="currentColor" />
          <path d="M6.125 18.5H4.625V17H6.125V18.5Z" fill="currentColor" />
          <path d="M8.375 18.5H6.875V17H8.375V18.5Z" fill="currentColor" />
        </g>
        <path
          d="M18.625 12.375H19V12.75H19.375V14.25H19V15H16V14.25H15.625V12.75H16V12.375H16.375V11.625H18.625V12.375Z"
          fill="currentColor"
        />
        <path d="M15.625 12H14.125V10.5H15.625V12Z" fill="currentColor" />
        <path d="M20.875 12H19.375V10.5H20.875V12Z" fill="currentColor" />
        <path d="M17.125 10.5H15.625V9H17.125V10.5Z" fill="currentColor" />
        <path d="M19.375 10.5H17.875V9H19.375V10.5Z" fill="currentColor" />
      </g>

      {/* State 5 */}
      <g className="state-5">
        <rect
          x="-156.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
        <path
          d="M7.625 4.375H8V4.75H8.375V6.25H8V7H5V6.25H4.625V4.75H5V4.375H5.375V3.625H7.625V4.375Z"
          fill="currentColor"
        />
        <path d="M4.625 4H3.125V2.5H4.625V4Z" fill="currentColor" />
        <path d="M9.875 4H8.375V2.5H9.875V4Z" fill="currentColor" />
        <path d="M6.125 2.5H4.625V1H6.125V2.5Z" fill="currentColor" />
        <path d="M8.375 2.5H6.875V1H8.375V2.5Z" fill="currentColor" />
        <g opacity="0.25">
          <path
            d="M18.625 12.375H19V12.75H19.375V14.25H19V15H16V14.25H15.625V12.75H16V12.375H16.375V11.625H18.625V12.375Z"
            fill="currentColor"
          />
          <path d="M15.625 12H14.125V10.5H15.625V12Z" fill="currentColor" />
          <path d="M20.875 12H19.375V10.5H20.875V12Z" fill="currentColor" />
          <path d="M17.125 10.5H15.625V9H17.125V10.5Z" fill="currentColor" />
          <path d="M19.375 10.5H17.875V9H19.375V10.5Z" fill="currentColor" />
        </g>
      </g>

      {/* State 6 */}
      <g className="state-6">
        <rect
          x="-190.5"
          y="-19.5"
          width="230.242"
          height="63"
          rx="4.5"
          stroke="#9747FF"
          strokeDasharray="10 5"
        />
        <g opacity="0.25">
          <path
            d="M7.625 4.375H8V4.75H8.375V6.25H8V7H5V6.25H4.625V4.75H5V4.375H5.375V3.625H7.625V4.375Z"
            fill="currentColor"
          />
          <path d="M4.625 4H3.125V2.5H4.625V4Z" fill="currentColor" />
          <path d="M9.875 4H8.375V2.5H9.875V4Z" fill="currentColor" />
          <path d="M6.125 2.5H4.625V1H6.125V2.5Z" fill="currentColor" />
          <path d="M8.375 2.5H6.875V1H8.375V2.5Z" fill="currentColor" />
        </g>
      </g>
    </svg>
  );
};

export default AnimatedProcessingIcon;
