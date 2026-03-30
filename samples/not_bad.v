module not_bad(a, y);
input a;
output reg y;

always @(*) begin
  y <= ~a;
end

endmodule