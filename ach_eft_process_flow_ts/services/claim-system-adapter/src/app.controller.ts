import { Body, Controller, Get, Post } from '@nestjs/common';
import { AppService } from './app.service';

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get('health')
  health() {
    return { status: 'ok', service: 'claim-system-adapter' };
  }

  @Post('claim')
  async handle(@Body() body: any) {
    return this.appService.publishEvent(body);
  }
}
